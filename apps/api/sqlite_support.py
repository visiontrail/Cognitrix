"""Shared SQLite connection setup for every state store in the API.

Almost every module here keeps its own small store (workspaces, chat history,
table catalog, users, ingestion jobs, views, ...) and most of them resolve to the
*same* file — ``state/ai_views.sqlite3``.  Opening those with the stdlib defaults
means the legacy rollback journal plus a 5 second busy timeout, so any writer
that stalls turns every concurrent write into
``sqlite3.OperationalError: database is locked`` (an unhandled 500).

Routing all connects through here gives two properties the defaults do not:

* **WAL journal mode** — readers never block the writer and the writer never
  blocks readers, so the polling GETs the web client issues cannot stall a
  commit.  The mode is persisted in the database file itself, so setting it once
  per file is enough.
* **A real busy timeout** — brief write contention waits and retries inside
  SQLite instead of failing the request.

``synchronous`` is deliberately left at its default: WAL alone removes the
contention problem, and lowering durability is not needed to do it.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger("cognitrix.sqlite")

# Busy timeout used when settings are unavailable (import-time helpers, tests
# that build a store directly, migration scripts).
DEFAULT_BUSY_TIMEOUT_MS = 15_000

_wal_lock = threading.Lock()
_wal_ready: set[str] = set()

# The timeout is read from *bootstrap* settings, never `get_settings()`:
# effective settings load admin overrides out of SQLite, so asking them here
# would re-enter this helper while the admin store's construction lock is held
# and deadlock.  The guard below keeps that true if config ever grows another
# SQLite-backed source.
_resolving = threading.local()

# get_bootstrap_settings() re-reads .env and re-validates the model on every
# call, and connections are opened per request — so the resolved value is
# memoized.  This is deployment configuration, not a runtime knob.
_timeout_lock = threading.Lock()
_timeout_ms: int | None = None


def busy_timeout_ms() -> int:
    """Configured busy timeout in milliseconds, falling back to the default."""
    global _timeout_ms
    with _timeout_lock:
        if _timeout_ms is not None:
            return _timeout_ms
    if getattr(_resolving, "active", False):
        return DEFAULT_BUSY_TIMEOUT_MS
    _resolving.active = True
    try:
        from .config import get_bootstrap_settings

        value = int(get_bootstrap_settings().sqlite_busy_timeout_ms)
    except Exception:  # pragma: no cover - settings unavailable (scripts/tests)
        return DEFAULT_BUSY_TIMEOUT_MS
    finally:
        _resolving.active = False
    resolved = value if value > 0 else DEFAULT_BUSY_TIMEOUT_MS
    with _timeout_lock:
        _timeout_ms = resolved
    return resolved


def _apply_wal(conn: sqlite3.Connection, db_path: Path) -> None:
    """Switch the database file to WAL once per process, best effort.

    WAL is a persistent property of the file, so a single successful attempt
    covers every later connection.  A failure (read-only mount, a network
    filesystem that does not support shared memory, another connection holding a
    lock at exactly this moment) is not fatal — the busy timeout still applies —
    so it is logged and retried on the next connect.
    """
    key = str(db_path)
    with _wal_lock:
        if key in _wal_ready:
            return
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()
    except sqlite3.Error as exc:  # pragma: no cover - filesystem dependent
        logger.warning("sqlite_wal_pragma_failed path=%s error=%s", key, exc)
        return
    if mode and str(mode[0]).lower() == "wal":
        with _wal_lock:
            _wal_ready.add(key)
    else:  # pragma: no cover - filesystem dependent
        logger.warning("sqlite_wal_not_applied path=%s journal_mode=%s", key, mode)


def connect(
    db_path: Path | str,
    *,
    row_factory: type[sqlite3.Row] | None = sqlite3.Row,
    foreign_keys: bool | None = None,
    create_parents: bool = False,
) -> sqlite3.Connection:
    """Open a SQLite connection with WAL and a busy timeout already applied.

    ``foreign_keys`` mirrors the per-store ``PRAGMA foreign_keys`` each caller
    used before: ``None`` leaves SQLite's default (off), ``True``/``False`` set
    it explicitly (``db_migrations`` needs it off while rewriting tables).
    """
    path = Path(db_path)
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    timeout_ms = busy_timeout_ms()
    conn = sqlite3.connect(path, timeout=timeout_ms / 1000)
    if row_factory is not None:
        conn.row_factory = row_factory
    # `timeout=` only covers the Python-level retry loop; the pragma is what
    # applies inside SQLite itself (including statements run by the C layer).
    conn.execute(f"PRAGMA busy_timeout={timeout_ms}")
    _apply_wal(conn, path)
    if foreign_keys is not None:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return conn


def reset_caches() -> None:
    """Forget the resolved timeout and which files already have WAL applied.

    Tests that change ``SQLITE_BUSY_TIMEOUT_MS`` or point at a fresh temp path
    call this the way they call ``get_settings.cache_clear()``.
    """
    global _timeout_ms
    with _timeout_lock:
        _timeout_ms = None
    with _wal_lock:
        _wal_ready.clear()
