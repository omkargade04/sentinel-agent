-- Migration: 002_workflow_run_events.sql
-- Purpose: Create workflow_run_events table for SSE progress tracking
-- Date: 2026-01-29
-- Description: Stores workflow progress events emitted by Temporal activities.
--              Enables real-time SSE streaming to frontend and provides audit trail.

BEGIN;

-- ============================================================================
-- CREATE WORKFLOW_RUN_EVENTS TABLE
-- Event store for SSE streaming and audit trail
-- ============================================================================

CREATE TABLE workflow_run_events (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Workflow identification
    workflow_id VARCHAR(255) NOT NULL,           -- Temporal workflow ID (e.g., "repo-index-123-main")
    workflow_run_id VARCHAR(255) NOT NULL,       -- Temporal run ID
    workflow_type VARCHAR(100) NOT NULL,         -- 'repo_indexing' | 'pr_review'

    -- Security/ownership context
    user_id UUID REFERENCES users(user_id),      -- For authorization checks
    installation_id BIGINT,                      -- GitHub installation
    repo_id UUID REFERENCES repositories(id),

    -- Event ordering (monotonic counter per workflow)
    sequence_number INT NOT NULL,

    -- Event content
    activity_name VARCHAR(100),                  -- e.g., 'clone_repo_activity'
    event_type VARCHAR(50) NOT NULL,             -- 'started' | 'progress' | 'completed' | 'failed'
    message TEXT NOT NULL,                       -- Human-readable message
    metadata JSONB NOT NULL DEFAULT '{}',        -- Activity-specific data

    -- Timestamp
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- CREATE INDEXES
-- Optimized for SSE polling and audit queries
-- ============================================================================

-- Unique constraint ensures no duplicate sequence numbers per workflow
-- Also serves as primary query index for SSE endpoint
CREATE UNIQUE INDEX idx_workflow_events_unique_sequence
ON workflow_run_events(workflow_id, sequence_number);

-- Composite index for efficient SSE queries (poll for events > last_seq)
CREATE INDEX idx_workflow_events_workflow
ON workflow_run_events(workflow_id, sequence_number);

-- Index for user queries (audit trail, user dashboards)
CREATE INDEX idx_workflow_events_user
ON workflow_run_events(user_id, created_at DESC);

-- Index for repo-based queries
CREATE INDEX idx_workflow_events_repo
ON workflow_run_events(repo_id, created_at DESC)
WHERE repo_id IS NOT NULL;

-- Index for workflow type filtering
CREATE INDEX idx_workflow_events_type
ON workflow_run_events(workflow_type, created_at DESC);

-- ============================================================================
-- ADD CONSTRAINTS
-- Ensure data integrity
-- ============================================================================

-- Validate event_type values
ALTER TABLE workflow_run_events ADD CONSTRAINT workflow_run_events_event_type_check
    CHECK (event_type IN ('workflow_started', 'started', 'progress', 'completed', 'failed', 'workflow_completed', 'workflow_failed'));

-- Validate workflow_type values
ALTER TABLE workflow_run_events ADD CONSTRAINT workflow_run_events_workflow_type_check
    CHECK (workflow_type IN ('repo_indexing', 'pr_review'));

-- Ensure sequence_number is positive
ALTER TABLE workflow_run_events ADD CONSTRAINT workflow_run_events_sequence_positive
    CHECK (sequence_number > 0);

-- ============================================================================
-- ADD DOCUMENTATION
-- ============================================================================

COMMENT ON TABLE workflow_run_events IS
    'Stores workflow progress events emitted by Temporal activities for SSE streaming and audit trail.';

COMMENT ON COLUMN workflow_run_events.workflow_id IS
    'Temporal workflow ID (e.g., repo-index-123-main). Used for SSE subscriptions.';

COMMENT ON COLUMN workflow_run_events.workflow_run_id IS
    'Temporal run ID for correlation with specific workflow execution.';

COMMENT ON COLUMN workflow_run_events.workflow_type IS
    'Type of workflow: repo_indexing or pr_review. Enables filtering and analytics.';

COMMENT ON COLUMN workflow_run_events.user_id IS
    'User who triggered the workflow. Used for authorization in SSE endpoint.';

COMMENT ON COLUMN workflow_run_events.sequence_number IS
    'Monotonic counter per workflow. Enables ordered delivery and reconnection support.';

COMMENT ON COLUMN workflow_run_events.activity_name IS
    'Name of the Temporal activity that emitted this event (e.g., clone_repo_activity).';

COMMENT ON COLUMN workflow_run_events.event_type IS
    'Event type: started, progress, completed, failed, or workflow-level events.';

COMMENT ON COLUMN workflow_run_events.message IS
    'Human-readable progress message for frontend display.';

COMMENT ON COLUMN workflow_run_events.metadata IS
    'Activity-specific data in JSONB format (file counts, SHAs, error details, etc.).';

-- ============================================================================
-- VALIDATION
-- Verify the migration was applied correctly
-- ============================================================================

DO $$
BEGIN
    -- Check table exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'workflow_run_events'
    ) THEN
        RAISE EXCEPTION 'workflow_run_events table not created';
    END IF;

    -- Check all required columns exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workflow_run_events'
        AND column_name = 'workflow_id'
    ) THEN
        RAISE EXCEPTION 'workflow_id column missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'workflow_run_events'
        AND column_name = 'sequence_number'
    ) THEN
        RAISE EXCEPTION 'sequence_number column missing';
    END IF;

    -- Check indexes exist
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_workflow_events_unique_sequence'
    ) THEN
        RAISE EXCEPTION 'unique sequence index missing';
    END IF;

    RAISE NOTICE 'Migration validation passed - workflow_run_events table created successfully';
END $$;

COMMIT;

-- ============================================================================
-- MIGRATION COMPLETE
-- Summary: Created workflow_run_events table for SSE progress tracking
-- - Main table with 12 columns
-- - 5 performance indexes
-- - 3 check constraints
-- - Full documentation
-- ============================================================================
