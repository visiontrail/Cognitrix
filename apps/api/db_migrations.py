from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
import string
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import get_settings
from .sqlite_support import connect as sqlite_connect

logger = logging.getLogger("cognitrix.db_migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
SQLITE_RELATIVE_BASE = Path(__file__).resolve().parent

MIGRATION_FILES = [
    "0003_workspace_agentic_ingestion_init.sql",
    "0004_published_pages_init.sql",
    "0005_users_and_collab.sql",
    "0006_workspace_state_init.sql",
]

_ALTER_STATEMENTS = [
    "ALTER TABLE users ADD COLUMN password_hash",
    "ALTER TABLE users ADD COLUMN email_lower",
    "ALTER TABLE users ADD COLUMN job_id",
    "ALTER TABLE users ADD COLUMN last_login_at",
    "ALTER TABLE workspace_members ADD COLUMN added_by",
    "ALTER TABLE published_pages ADD COLUMN visibility_mode",
    "ALTER TABLE published_pages ADD COLUMN visibility_user_ids",
]

JOB_SEEDS = [
    ("developer", "开发者", "Developer", 1),
    ("pm", "项目经理", "Project Manager", 2),
    ("team_leader", "Team Leader", "Team Leader", 3),
    ("product_manager", "产品经理", "Product Manager", 4),
    ("hr", "人力资源", "HR", 5),
    ("data_analyst", "数据分析师", "Data Analyst", 6),
    ("other", "其他", "Other", 7),
]


def _get_db_path() -> Path:
    settings = get_settings()
    db_url = settings.database_url.strip()
    if db_url.startswith("sqlite://"):
        parsed = urlparse(db_url)
        raw_path = unquote(parsed.path)
        if raw_path.startswith("//"):
            return Path("/" + raw_path.lstrip("/")).resolve()
        if raw_path.startswith("/") and len(raw_path) > 1 and raw_path[1] != ".":
            return Path(raw_path).resolve()
        if raw_path.startswith("/"):
            raw_path = raw_path[1:]
        return (SQLITE_RELATIVE_BASE / raw_path).resolve()
    return (settings.upload_dir / "state" / "ai_views.sqlite3").resolve()


def _connect(db_path: Path) -> sqlite3.Connection:
    return sqlite_connect(db_path, foreign_keys=False, create_parents=True)


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def _is_applied(conn: sqlite3.Connection, migration_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM _schema_migrations WHERE id = ?", (migration_id,)
    ).fetchone()
    return row is not None


def _mark_applied(conn: sqlite3.Connection, migration_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO _schema_migrations (id) VALUES (?)", (migration_id,)
    )
    conn.commit()


def _run_migration_sql(conn: sqlite3.Connection, sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        is_alter = any(stmt.upper().startswith(prefix.upper()) for prefix in _ALTER_STATEMENTS)
        try:
            conn.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError as exc:
            if is_alter and "duplicate column name" in str(exc).lower():
                logger.debug("column already exists, skipping: %s", stmt[:80])
            elif "already exists" in str(exc).lower():
                logger.debug("object already exists, skipping: %s", stmt[:80])
            else:
                raise


def _relax_business_type_constraint(conn: sqlite3.Connection) -> None:
    """Drop the closed-vocabulary CHECK on table_catalog.business_type.

    The original schema restricted business_type to
    {roster, project_progress, attendance, other}. The Write Ingestion Agent
    is now allowed to propose free-form snake_case labels (project_assignment,
    sales_pipeline, …). SQLite has no in-place CHECK drop, so rebuild the
    table inside a single transaction. Idempotent: returns immediately if the
    current schema no longer contains the closed CHECK list.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'table_catalog'"
    ).fetchone()
    if row is None:
        return
    schema_sql = str(row["sql"] or "")
    if "business_type" not in schema_sql:
        return
    # The closed-vocabulary signature is the literal IN-list on business_type.
    if "business_type IN ('roster'" not in schema_sql:
        return

    logger.info("relaxing table_catalog.business_type CHECK constraint")
    try:
        conn.execute("BEGIN")
        conn.execute(
            """
            CREATE TABLE table_catalog__relaxed (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                table_name TEXT NOT NULL,
                human_label TEXT NOT NULL,
                business_type TEXT NOT NULL,
                write_mode TEXT NOT NULL CHECK (write_mode IN (
                    'update_existing', 'time_partitioned_new_table', 'new_table', 'append_only'
                )),
                time_grain TEXT NOT NULL CHECK (time_grain IN ('none', 'month', 'quarter', 'year')),
                primary_keys TEXT NOT NULL DEFAULT '[]',
                match_columns TEXT NOT NULL DEFAULT '[]',
                is_active_target INTEGER NOT NULL DEFAULT 1,
                description TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
                FOREIGN KEY (created_by) REFERENCES users(id),
                FOREIGN KEY (updated_by) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO table_catalog__relaxed (
                id, workspace_id, table_name, human_label, business_type, write_mode,
                time_grain, primary_keys, match_columns, is_active_target, description,
                created_by, updated_by, created_at, updated_at
            )
            SELECT id, workspace_id, table_name, human_label, business_type, write_mode,
                   time_grain, primary_keys, match_columns, is_active_target, description,
                   created_by, updated_by, created_at, updated_at
            FROM table_catalog
            """
        )
        conn.execute("DROP INDEX IF EXISTS idx_table_catalog_workspace_business")
        conn.execute("DROP TABLE table_catalog")
        conn.execute("ALTER TABLE table_catalog__relaxed RENAME TO table_catalog")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_table_catalog_workspace_business "
            "ON table_catalog(workspace_id, business_type, is_active_target)"
        )
        conn.execute("COMMIT")
        logger.info("table_catalog business_type CHECK relaxed")
    except sqlite3.DatabaseError:
        conn.execute("ROLLBACK")
        raise


def _seed_jobs(conn: sqlite3.Connection) -> None:
    for code, label_zh, label_en, sort_order in JOB_SEEDS:
        conn.execute(
            """
            INSERT OR IGNORE INTO user_jobs (code, label_zh, label_en, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (code, label_zh, label_en, sort_order),
        )
    conn.commit()


def _generate_bootstrap_password() -> str:
    """A password nobody has to invent, transmit, or store in a manifest.

    Alphanumeric only: the value is read off a terminal and retyped into a
    login form, so shell quoting and character-set surprises cost more than the
    handful of entropy bits. 20 characters from a 62-symbol alphabet is ~119
    bits, far past anything a login form can be brute-forced through.
    """

    alphabet = string.ascii_letters + string.digits
    return "Cg" + "".join(secrets.choice(alphabet) for _ in range(20))


def _log_generated_credentials(email: str, password: str) -> None:
    """Announce a generated credential loudly enough to be found in pod logs.

    This is the only place the password is ever readable: it is bcrypt-hashed
    before it reaches the database, and this line is emitted once, at account
    creation. WARNING level so it survives a deployment that filters INFO.
    """

    logger.warning(
        "\n"
        "================================================================\n"
        " COGNITRIX BOOTSTRAP ADMIN CREATED\n"
        "   email:    %s\n"
        "   password: %s\n"
        "\n"
        " Shown once, at account creation, and never logged again.\n"
        " Change it immediately after the first login.\n"
        " Set AUTH_BOOTSTRAP_ADMIN_PASSWORD to choose the password instead.\n"
        "================================================================",
        email,
        password,
    )


def _bootstrap_admin(conn: sqlite3.Connection) -> None:
    settings = get_settings()
    admin_email = settings.auth_bootstrap_admin_email.strip()
    # An explicitly empty email opts out of bootstrapping entirely; the field
    # otherwise carries a default so a zero-configuration deployment still ends
    # up with an account somebody can log in with.
    if not admin_email:
        return

    row = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE password_hash IS NOT NULL").fetchone()
    if row and int(row["cnt"]) > 0:
        return

    # Only reached while the deployment has no password account at all, so the
    # generated credential can never overwrite one somebody is already using.
    admin_password = settings.auth_bootstrap_admin_password.strip()
    generated = not admin_password
    if generated:
        admin_password = _generate_bootstrap_password()

    import bcrypt as _bcrypt_lib

    salt = _bcrypt_lib.gensalt()
    password_hash = _bcrypt_lib.hashpw(admin_password.encode("utf-8"), salt).decode("utf-8")
    email_lower = admin_email.lower()

    import uuid as _uuid
    user_id = _uuid.uuid4().hex
    job_row = conn.execute("SELECT id FROM user_jobs WHERE code = 'developer'").fetchone()
    job_id = int(job_row["id"]) if job_row else None

    conn.execute(
        """
        INSERT INTO users (id, email, email_lower, display_name, password_hash, job_id, status, created_at, updated_at)
        VALUES (?, ?, ?, 'Admin', ?, ?, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(email_lower) DO NOTHING
        """,
        (user_id, admin_email, email_lower, password_hash, job_id),
    )
    conn.commit()
    logger.info("bootstrap_admin_created email=%s generated_password=%s", admin_email, generated)
    if generated:
        _log_generated_credentials(admin_email, admin_password)


def _bootstrap_superadmin(conn: sqlite3.Connection) -> None:
    """Promote the configured account to the `superadmin` role on startup.

    - When `AUTH_BOOTSTRAP_SUPERADMIN_EMAIL` is set and the user exists, promote them.
    - Otherwise, if no user currently has the `superadmin` role override and a
      bootstrap admin user exists, promote the bootstrap admin so the operator is
      never locked out of /admin/skills.
    """
    from .auth import clear_auth_cache, get_role_directory
    from .audit import get_audit_logger

    settings = get_settings()
    role_dir = get_role_directory()

    def _promote(user_id: str, email_lower: str, reason: str) -> None:
        existing = role_dir.get_override(user_id) or {}
        if str(existing.get("role", "")).lower() == "superadmin":
            return
        role_dir.set_override(
            user_id=user_id,
            role="superadmin",
            department=existing.get("department"),
            clearance=int(existing.get("clearance", 0)),
            updated_by="bootstrap",
        )
        clear_auth_cache()
        get_audit_logger().log(
            event_type="authorization",
            action="superadmin_promote",
            status="success",
            severity="ALERT",
            user_id=user_id,
            project_id="default",
            resource="auth.superadmin",
            detail={"reason": reason, "email": email_lower},
        )
        logger.info("superadmin_promoted user_id=%s reason=%s", user_id, reason)

    target_email = settings.auth_bootstrap_superadmin_email.strip().lower()
    if target_email:
        row = conn.execute(
            "SELECT id, COALESCE(email_lower, LOWER(email)) AS email_lower "
            "FROM users WHERE COALESCE(email_lower, LOWER(email)) = ?",
            (target_email,),
        ).fetchone()
        if row is not None:
            _promote(str(row["id"]), str(row["email_lower"]), reason="env_var")
            return
        logger.warning("superadmin_bootstrap_user_missing email=%s", target_email)
        return

    # No env override — only auto-promote if there is no existing superadmin.
    if role_dir.has_any_with_role("superadmin"):
        return

    admin_email = settings.auth_bootstrap_admin_email.strip().lower()
    if not admin_email:
        return
    row = conn.execute(
        "SELECT id, COALESCE(email_lower, LOWER(email)) AS email_lower "
        "FROM users WHERE COALESCE(email_lower, LOWER(email)) = ?",
        (admin_email,),
    ).fetchone()
    if row is not None:
        _promote(str(row["id"]), str(row["email_lower"]), reason="bootstrap_admin_fallback")


def apply_migrations() -> None:
    db_path = _get_db_path()
    conn = _connect(db_path)
    try:
        _ensure_migrations_table(conn)
        for filename in MIGRATION_FILES:
            migration_id = filename
            sql_path = MIGRATIONS_DIR / filename
            if not sql_path.exists():
                logger.warning("migration_file_missing path=%s", sql_path)
                continue
            if _is_applied(conn, migration_id):
                logger.debug("migration_already_applied id=%s", migration_id)
                continue
            logger.info("applying_migration id=%s", migration_id)
            _run_migration_sql(conn, sql_path)
            _mark_applied(conn, migration_id)
            logger.info("migration_applied id=%s", migration_id)

        _relax_business_type_constraint(conn)
        _add_workspace_id_to_ai_views(conn)
        _seed_jobs(conn)
        _bootstrap_admin(conn)
        _bootstrap_superadmin(conn)
    finally:
        conn.close()


def _add_workspace_id_to_ai_views(conn: sqlite3.Connection) -> None:
    """Backfill the ai_views table with a workspace_id column so workspace
    delete-cascade can reach saved views.

    Idempotent: skips when the column is already present. We don't try to
    derive workspace_id from legacy owner_project_id (different concept) —
    pre-existing rows just get NULL and remain accessible by view_id; only
    NEW saves (which now plumb workspace_id) participate in the cascade.

    Note: agent_sessions.workspace_id is handled inside
    AgentSessionStore._init_schema because that table lives in a different
    SQLite file (state/agent_sessions.sqlite3) than the one this migration
    runner operates on (ai_views.sqlite3 / DATABASE_URL).
    """
    if not _table_exists(conn, "ai_views"):
        return
    if _column_exists(conn, "ai_views", "workspace_id"):
        return
    conn.execute("ALTER TABLE ai_views ADD COLUMN workspace_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_views_workspace ON ai_views(workspace_id)"
    )
    conn.commit()
    logger.info("ai_views workspace_id column added")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r[1]) == column for r in rows)
