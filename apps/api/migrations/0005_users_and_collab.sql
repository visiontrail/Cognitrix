-- M5: user accounts, collaboration, and publish visibility

-- Extend users table with auth fields
ALTER TABLE users ADD COLUMN password_hash TEXT;
ALTER TABLE users ADD COLUMN email_lower TEXT;
ALTER TABLE users ADD COLUMN job_id INTEGER REFERENCES user_jobs(id);
ALTER TABLE users ADD COLUMN last_login_at TIMESTAMP;

-- Ensure email_lower is populated for existing rows
UPDATE users SET email_lower = LOWER(email) WHERE email_lower IS NULL;

-- Unique index on email_lower for case-insensitive lookup
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_lower ON users(email_lower);

-- Job/position lookup table
CREATE TABLE IF NOT EXISTS user_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    label_zh TEXT NOT NULL,
    label_en TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    parent_id INTEGER
);

-- Seed default jobs (idempotent)
INSERT OR IGNORE INTO user_jobs (code, label_zh, label_en, sort_order)
VALUES
    ('developer',         '开发者',     'Developer',        1),
    ('pm',                '项目经理',   'Project Manager',  2),
    ('team_leader',       'Team Leader','Team Leader',      3),
    ('product_manager',   '产品经理',   'Product Manager',  4),
    ('hr',                '人力资源',   'HR',               5),
    ('data_analyst',      '数据分析师', 'Data Analyst',     6),
    ('other',             '其他',       'Other',            7);

-- Extend workspace_members with added_by
ALTER TABLE workspace_members ADD COLUMN added_by TEXT;

-- Workspace invite links
CREATE TABLE IF NOT EXISTS workspace_invites (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('editor', 'viewer')),
    created_by TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    used_count INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_invites_workspace
    ON workspace_invites(workspace_id, revoked_at);

-- Extend published_pages with visibility columns
ALTER TABLE published_pages ADD COLUMN visibility_mode TEXT NOT NULL DEFAULT 'public'
    CHECK (visibility_mode IN ('public', 'private', 'registered', 'allowlist'));
ALTER TABLE published_pages ADD COLUMN visibility_user_ids TEXT;
