CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    supabase_user_id UUID NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS github_installations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id BIGINT NOT NULL UNIQUE,
    github_account_id BIGINT NOT NULL,
    github_account_type VARCHAR(255) NOT NULL,
    user_id UUID REFERENCES users(user_id) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS github_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id BIGINT REFERENCES github_installations(installation_id) NOT NULL,
    credential_type VARCHAR DEFAULT 'installation',
    encrypted_token TEXT NOT NULL,
    token_expires_at TIMESTAMP NOT NULL,
    scope TEXT[],
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS repositories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    installation_id BIGINT REFERENCES github_installations(installation_id) NOT NULL,
    github_repo_id BIGINT NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    default_branch VARCHAR(255) NOT NULL,
    private BOOLEAN DEFAULT FALSE,
    last_synced_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS repository_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id) NOT NULL,
    settings JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE repo_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id),
    commit_sha VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS indexed_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id),
    snapshot_id UUID REFERENCES repo_snapshots(id),
    file_path VARCHAR NOT NULL,
    language VARCHAR NOT NULL,
    indexed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS symbols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id),
    snapshot_id UUID REFERENCES repo_snapshots(id),
    symbol_name VARCHAR NOT NULL,
    symbol_kind VARCHAR NOT NULL,
    file_path VARCHAR NOT NULL,
    span_start_line INT NOT NULL,
    span_end_line INT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE symbol_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID REFERENCES repo_snapshots(id),
    source_symbol_id UUID REFERENCES symbols(id),
    target_symbol_id UUID REFERENCES symbols(id),
    edge_type VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE EXTENSION vector; 

CREATE TABLE IF NOT EXISTS symbol_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID REFERENCES repo_snapshots(id),
    symbol_id UUID REFERENCES symbols(id),
    embedding VECTOR(1536),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pull_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id),
    pr_number BIGINT NOT NULL,
    author_github_id BIGINT NOT NULL,
    title VARCHAR NOT NULL,
    body TEXT,
    base_branch VARCHAR,
    head_branch VARCHAR,
    base_sha VARCHAR,
    head_sha VARCHAR,
    state VARCHAR DEFAULT 'open',
    merged_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pr_file_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pr_id UUID REFERENCES pull_requests(id),
    file_path VARCHAR NOT NULL,
    change_type VARCHAR NOT NULL, -- ADDED, MODIFIED, DELETED
    additions INT NOT NULL,
    deletions INT NOT NULL,
    diff TEXT
);

CREATE TABLE IF NOT EXISTS review_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pr_id UUID REFERENCES pull_requests(id),
    llm_model VARCHAR,
    head_sha VARCHAR,
    snapshot_id UUID REFERENCES repo_snapshots(id),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR DEFAULT 'pending',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS review_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_run_id UUID REFERENCES review_runs(id),
    file_path VARCHAR NOT NULL,
    line_number INT NOT NULL,
    finding_type VARCHAR NOT NULL, -- BUG, SECURITY, PERFORMANCE, etc.
    severity VARCHAR NOT NULL, -- LOW, MEDIUM, HIGH, CRITICAL
    message TEXT NOT NULL,
    suggestion TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR NOT NULL, -- REVIEW_RUN, SYMBOL_INDEXING, etc.
    status VARCHAR DEFAULT 'pending', -- pending, in_progress, completed, failed
    payload JSONB NOT NULL,
    retry_count INT DEFAULT 0,
    max_retries INT DEFAULT 3,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS automation_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repository_id UUID REFERENCES repositories(id),
    name VARCHAR,
    trigger_event VARCHAR, -- e.g. pr_opened, pr_merged
    actions JSONB, -- list of actions to be executed
    is_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES automation_workflows(id),
    status VARCHAR,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_symbols_repo ON symbols(repository_id);
CREATE INDEX idx_symbols_snapshot ON symbols(snapshot_id);
CREATE INDEX idx_embeddings_symbol ON symbol_embeddings(symbol_id);
CREATE INDEX idx_pr_repo ON pull_requests(repository_id);
CREATE INDEX idx_review_run_pr ON review_runs(pr_id);