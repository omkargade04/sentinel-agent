-- Migration: 001_pr_review_extensions.sql
-- Purpose: Add minimal PR review pipeline extensions to existing schema
-- Date: 2026-01-15
-- Description: Extends existing review_runs and review_findings tables with 5 essential fields
--              for Temporal workflow tracking, GitHub publishing, and diff anchoring

BEGIN;

-- ============================================================================
-- EXTEND REVIEW_RUNS TABLE
-- Add Temporal workflow tracking and GitHub publishing status fields
-- ============================================================================

-- Add Temporal workflow integration field
ALTER TABLE review_runs
ADD COLUMN temporal_workflow_id VARCHAR(255) NULL;

-- Add GitHub review publishing fields
ALTER TABLE review_runs
ADD COLUMN github_review_id BIGINT NULL;

ALTER TABLE review_runs
ADD COLUMN published BOOLEAN DEFAULT FALSE NOT NULL;

-- ============================================================================
-- EXTEND REVIEW_FINDINGS TABLE
-- Add diff anchoring and GitHub comment tracking fields
-- ============================================================================

-- Add diff anchoring field for inline comment positioning
ALTER TABLE review_findings
ADD COLUMN hunk_id VARCHAR(100) NULL;

-- Add GitHub comment tracking field
ALTER TABLE review_findings
ADD COLUMN github_comment_id BIGINT NULL;

-- ============================================================================
-- CREATE PERFORMANCE INDEXES
-- Essential indexes for efficient queries on new fields
-- ============================================================================

-- Index for Temporal workflow lookup (debugging and monitoring)
CREATE INDEX CONCURRENTLY idx_review_runs_temporal_workflow_id
ON review_runs(temporal_workflow_id)
WHERE temporal_workflow_id IS NOT NULL;

-- Index for published status queries (metrics and analytics)
CREATE INDEX CONCURRENTLY idx_review_runs_published
ON review_runs(published);

-- Index for GitHub review lookup (audit trail queries)
CREATE INDEX CONCURRENTLY idx_review_runs_github_review_id
ON review_runs(github_review_id)
WHERE github_review_id IS NOT NULL;

-- Index for diff anchoring queries (finding anchorable comments)
CREATE INDEX CONCURRENTLY idx_review_findings_hunk_id
ON review_findings(hunk_id)
WHERE hunk_id IS NOT NULL;

-- Index for GitHub comment tracking (published comment lookup)
CREATE INDEX CONCURRENTLY idx_review_findings_github_comment_id
ON review_findings(github_comment_id)
WHERE github_comment_id IS NOT NULL;

-- ============================================================================
-- UPDATE TABLE CONSTRAINTS
-- Ensure data integrity and valid enum values
-- ============================================================================

-- Update status constraint to include new workflow status values
ALTER TABLE review_runs DROP CONSTRAINT IF EXISTS review_runs_status_check;
ALTER TABLE review_runs ADD CONSTRAINT review_runs_status_check
    CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'cancelled'));

-- Ensure published is always non-null (defensive constraint)
ALTER TABLE review_runs ALTER COLUMN published SET NOT NULL;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- Document the purpose of each new field
-- ============================================================================

COMMENT ON COLUMN review_runs.temporal_workflow_id IS
    'Temporal workflow ID for correlation with workflow execution. Used for debugging and monitoring.';

COMMENT ON COLUMN review_runs.github_review_id IS
    'GitHub review ID when successfully published. Provides audit trail for published reviews.';

COMMENT ON COLUMN review_runs.published IS
    'Quick flag indicating if review was successfully published to GitHub. Used for metrics queries.';

COMMENT ON COLUMN review_findings.hunk_id IS
    'Diff hunk identifier for anchoring findings to specific diff positions. Enables inline comments.';

COMMENT ON COLUMN review_findings.github_comment_id IS
    'GitHub comment ID when finding is published as inline comment. Tracks which findings became comments.';

-- ============================================================================
-- VALIDATION QUERIES
-- Verify the migration was applied correctly
-- ============================================================================

-- Validate all new columns exist and have correct types
DO $$
BEGIN
    -- Check review_runs extensions
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'review_runs'
        AND column_name = 'temporal_workflow_id'
        AND data_type = 'character varying'
    ) THEN
        RAISE EXCEPTION 'temporal_workflow_id column missing or wrong type';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'review_runs'
        AND column_name = 'github_review_id'
        AND data_type = 'bigint'
    ) THEN
        RAISE EXCEPTION 'github_review_id column missing or wrong type';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'review_runs'
        AND column_name = 'published'
        AND data_type = 'boolean'
    ) THEN
        RAISE EXCEPTION 'published column missing or wrong type';
    END IF;

    -- Check review_findings extensions
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'review_findings'
        AND column_name = 'hunk_id'
        AND data_type = 'character varying'
    ) THEN
        RAISE EXCEPTION 'hunk_id column missing or wrong type';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'review_findings'
        AND column_name = 'github_comment_id'
        AND data_type = 'bigint'
    ) THEN
        RAISE EXCEPTION 'github_comment_id column missing or wrong type';
    END IF;

    -- Validate indexes were created
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_review_runs_temporal_workflow_id'
    ) THEN
        RAISE EXCEPTION 'temporal_workflow_id index missing';
    END IF;

    RAISE NOTICE 'Migration validation passed - all 5 fields and indexes created successfully';
END $$;

COMMIT;

-- ============================================================================
-- MIGRATION COMPLETE
-- Summary: Added 5 essential fields for PR review pipeline
-- - review_runs: temporal_workflow_id, github_review_id, published (3 fields)
-- - review_findings: hunk_id, github_comment_id (2 fields)
-- - Created 5 performance indexes
-- - Updated constraints and added documentation
-- ============================================================================