# Temporal Workflows Module

## What

The workflows module defines Temporal workflows that orchestrate long-running, fault-tolerant business processes. Workflows coordinate activities in a deterministic, replayable manner.

## Why

Temporal workflows provide:
- **Reliability**: Automatic retries and failure recovery
- **Durability**: Workflow state persists across restarts
- **Determinism**: Replayable execution for debugging
- **Orchestration**: Coordinate multiple async activities
- **Visibility**: Workflow history and status tracking

## How

### Architecture

```
workflows/
├── repo_indexing_workflow.py    # Repository indexing orchestration
└── README.md                   # This file
```

### Key Workflows

#### RepoIndexingWorkflow (`repo_indexing_workflow.py`)

**Purpose**: Orchestrates the complete repository indexing pipeline.

**Workflow Definition**:
```python
@workflow.defn
class RepoIndexingWorkflow:
    @workflow.run
    async def run(self, repo_request: dict) -> dict:
        # Orchestration logic
```

**Input**:
```python
{
    "installation_id": int,
    "github_repo_name": str,
    "repo_id": str,
    "default_branch": str,
    "repo_url": str
}
```

**Output**:
```python
{
    "status": "success",
    "repo": "owner/repo",
    "commit_sha": "abc123...",
    "stats": {
        "total_symbols": 1500,
        "indexed_files": 200,
        ...
    },
    "stale_nodes_deleted": 50
}
```

### Workflow Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│          Repository Indexing Workflow Execution              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Clone Repository                                        │
│     Activity: clone_repo_activity                           │
│     ├── Generate installation token                        │
│     ├── Resolve commit SHA                                 │
│     └── Clone to /tmp/{repo_id}-{commit_sha}               │
│           ↓                                                 │
│  2. Parse Repository                                       │
│     Activity: parse_repo_activity                           │
│     ├── Walk directory tree                                │
│     ├── Parse files with Tree-sitter                        │
│     ├── Extract symbols                                    │
│     └── Build knowledge graph                               │
│           ↓                                                 │
│  3. Persist Metadata                                       │
│     Activity: persist_metadata_activity                    │
│     ├── Create repo_snapshots record                        │
│     ├── Upsert indexed_files records                        │
│     └── Update repositories table                           │
│           ↓                                                 │
│  4. Persist Knowledge Graph                                │
│     Activity: persist_kg_activity                           │
│     ├── Batch upsert nodes to Neo4j                        │
│     └── Batch upsert edges to Neo4j                         │
│           ↓                                                 │
│  5. Cleanup Stale Nodes                                   │
│     Activity: cleanup_stale_kg_nodes_activity              │
│     └── Remove nodes not refreshed in 7 days              │
│           ↓                                                 │
│  6. Cleanup Repository (finally block)                    │
│     Activity: cleanup_repo_activity                         │
│     └── Delete cloned repository directory                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Retry Policies

**Default Retry Policy**:
```python
retry_policy = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=10),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)
```

**Non-Retryable Policy**:
```python
no_retry_policy = RetryPolicy(maximum_attempts=1)
```
- Used for auth/404 errors (permanent failures)

### Activity Timeouts

| Activity | Timeout | Reason |
|----------|---------|--------|
| `clone_repo_activity` | 5 minutes | Network operations |
| `parse_repo_activity` | 5 minutes | CPU-intensive parsing |
| `persist_metadata_activity` | 5 minutes | Database operations |
| `persist_kg_activity` | 10 minutes | Large graph persistence |
| `cleanup_stale_kg_nodes_activity` | 5 minutes | Neo4j cleanup |
| `cleanup_repo_activity` | 2 minutes | File system operations |

### Error Handling

**Try-Except-Finally Pattern**:
```python
clone_result = None
try:
    # Main workflow logic
    clone_result = await workflow.execute_activity(...)
    # ... more activities
except Exception as e:
    workflow.logger.error(f"Workflow failed: {e}")
    raise
finally:
    # Always cleanup, even on failure
    if clone_result:
        await workflow.execute_activity(cleanup_repo_activity, ...)
```

**Benefits**:
- Ensures cleanup always happens
- Prevents resource leaks
- Logs errors for debugging

### Determinism Requirements

**Allowed**:
- ✅ Dict/list operations
- ✅ Workflow methods (`execute_activity`, `sleep`, etc.)
- ✅ Deterministic functions (no random, time, etc.)

**Not Allowed**:
- ❌ Random number generation
- ❌ Current time (`datetime.now()`)
- ❌ Non-deterministic operations
- ❌ User sessions/tokens (use installation_id instead)

**Example**:
```python
# ✅ Good: Deterministic
workflow_id = f"repo-index-{repo_request['repo_id']}-{repo_request['default_branch']}"

# ❌ Bad: Non-deterministic
workflow_id = f"repo-index-{uuid.uuid4()}"  # Different on replay!
```

### Workflow ID Strategy

**Pattern**: `repo-index-{repo_id}-{branch}`

**Benefits**:
- Deterministic: Same repo+branch = same workflow ID
- Prevents duplicate workflows
- Easy to query by repo

**Example**:
```python
workflow_id = f"repo-index-{repo_request['repo_id']}-{repo_request['default_branch']}"
# Result: "repo-index-repo-uuid-main"
```

### Logging

**Workflow Logger**:
```python
workflow.logger.info(f"Starting repository indexing workflow for {repo_name}")
workflow.logger.error(f"Failed to clone repository: {e}")
```

**Benefits**:
- Logs appear in Temporal UI
- Persistent across replays
- Useful for debugging

### Usage

**Starting a Workflow** (from API route):
```python
handle = await temporal_client.start_workflow(
    RepoIndexingWorkflow.run,
    repo_request.model_dump(mode="json"),
    id=workflow_id,
    task_queue="repo-indexing-queue",
)
```

**Querying Workflow Status**:
```python
handle = temporal_client.get_workflow_handle(workflow_id)
result = await handle.result()
```

**Canceling a Workflow**:
```python
await handle.cancel()
```

### Testing

```python
# Test workflow execution
async def test_repo_indexing_workflow():
    workflow = RepoIndexingWorkflow()
    result = await workflow.run({
        "installation_id": 123,
        "github_repo_name": "test/repo",
        "repo_id": "test-uuid",
        "default_branch": "main",
        "repo_url": "https://github.com/test/repo.git"
    })
    assert result["status"] == "success"
    assert "commit_sha" in result
```

### Design Decisions

1. **Dict Input/Output**: Avoids Pydantic serialization issues
2. **Finally Block**: Ensures cleanup always happens
3. **Retry Policies**: Configurable per activity
4. **Deterministic IDs**: Workflow IDs based on input data
5. **Error Propagation**: Let activities handle their own errors

### Dependencies

- **temporalio**: Temporal Python SDK
- **datetime**: For timeouts and intervals

### Configuration

- Task Queue: `repo-indexing-queue`
- Temporal Server: Configured in `core/temporal_client.py`

### Future Enhancements

- [ ] Workflow versioning for schema evolution
- [ ] Child workflows for parallel processing
- [ ] Workflow signals for user interaction
- [ ] Workflow queries for status updates
- [ ] Workflow timers for scheduled operations
- [ ] Workflow cancellation handling

