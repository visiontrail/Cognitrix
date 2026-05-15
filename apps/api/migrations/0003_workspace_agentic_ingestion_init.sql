-- M0 bootstrap schema for workspace-scoped agentic ingestion.

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users(email);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_slug ON workspaces(slug);

CREATE TABLE IF NOT EXISTS workspace_members (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_membership
    ON workspace_members(workspace_id, user_id);

CREATE TABLE IF NOT EXISTS table_catalog (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    human_label TEXT NOT NULL,
    business_type TEXT NOT NULL CHECK (business_type IN ('roster', 'project_progress', 'attendance', 'other')),
    write_mode TEXT NOT NULL CHECK (write_mode IN ('update_existing', 'time_partitioned_new_table', 'new_table', 'append_only')),
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
);

CREATE INDEX IF NOT EXISTS idx_table_catalog_workspace_business
    ON table_catalog(workspace_id, business_type, is_active_target);

CREATE TABLE IF NOT EXISTS table_column_metadata (
    workspace_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    original_name TEXT,
    description TEXT,
    data_type TEXT,
    ordinal_position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, table_name, column_name),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE INDEX IF NOT EXISTS idx_table_column_metadata_table
    ON table_column_metadata(workspace_id, table_name, ordinal_position);

CREATE TABLE IF NOT EXISTS ingestion_uploads (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    uploaded_by TEXT NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    size_bytes BIGINT NOT NULL,
    file_hash TEXT NOT NULL,
    sheet_summary TEXT NOT NULL DEFAULT '{}',
    column_summary TEXT NOT NULL DEFAULT '{}',
    sample_preview TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    upload_id TEXT NOT NULL,
    created_by TEXT NOT NULL,
    agent_session_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'uploaded',
            'planning',
            'awaiting_catalog_setup',
            'awaiting_user_approval',
            'approved',
            'executing',
            'succeeded',
            'failed',
            'cancelled'
        )
    ),
    business_type_guess TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (upload_id) REFERENCES ingestion_uploads(id),
    FOREIGN KEY (created_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_workspace_status
    ON ingestion_jobs(workspace_id, status);

CREATE TABLE IF NOT EXISTS ingestion_proposals (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    proposal_version INTEGER NOT NULL,
    proposal_json TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    target_table TEXT,
    predicted_insert_count INTEGER NOT NULL DEFAULT 0,
    predicted_update_count INTEGER NOT NULL DEFAULT 0,
    predicted_conflict_count INTEGER NOT NULL DEFAULT 0,
    risk_summary TEXT NOT NULL DEFAULT '[]',
    generated_sql_draft TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_proposal_version
    ON ingestion_proposals(job_id, proposal_version);

CREATE TABLE IF NOT EXISTS ingestion_executions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    executed_by TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    validated_sql TEXT NOT NULL,
    dry_run_summary TEXT NOT NULL DEFAULT '{}',
    execution_receipt TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id),
    FOREIGN KEY (proposal_id) REFERENCES ingestion_proposals(id),
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
    FOREIGN KEY (executed_by) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_executions_job_status
    ON ingestion_executions(job_id, status);

CREATE TABLE IF NOT EXISTS ingestion_events (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES ingestion_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_events_job_created
    ON ingestion_events(job_id, created_at);
