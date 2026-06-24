-- Server-side persistence for chat history, chart assets, and canvas snapshots.
-- These previously lived only in browser localStorage, so they did not survive a
-- move to another browser or device. Each table is workspace + user scoped and is
-- reaped by the workspace delete-cascade in workspaces.py.

CREATE TABLE IF NOT EXISTS chat_sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    last_message TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_ws_user
    ON chat_sessions(workspace_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'assistant',
    content TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, seq);

CREATE TABLE IF NOT EXISTS chart_assets (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    chart_type TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chart_assets_ws_user
    ON chart_assets(workspace_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS workspace_snapshots (
    workspace_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL DEFAULT '{}',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
