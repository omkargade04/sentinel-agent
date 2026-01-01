# Temporal Activities Module

## What

The activities module defines Temporal activities - the actual work units that perform non-deterministic operations. Activities wrap service layer business logic and handle Temporal-specific concerns like heartbeats and error handling.

## Why

Activities provide:
- **Non-Deterministic Operations**: Can perform I/O, network calls, random operations
- **Retry Logic**: Automatic retries with configurable policies
- **Heartbeats**: Progress reporting for long-running operations
- **Error Classification**: Distinguish retryable vs non-retryable errors
- **Isolation**: Failures in activities don't crash workflows

## How

### Architecture

```
activities/
├── indexing_activities.py    # Repository indexing activities
└── README.md               # This file
```

### Key Activities

#### 1. Clone Repo Activity (`clone_repo_activity`)

**Purpose**: Clones a GitHub repository securely.

**Signature**:
```python
@activity.defn
async def clone_repo_activity(repo_request: dict) -> dict:
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
    "local_path": "/tmp/repo-uuid-abc123",
    "commit_sha": "abc123..."
}
```

**Implementation**:
```python
service = RepoCloneService()
result = await service.clone_repo(...)
return result
```

**Error Handling**:
- Non-retryable: 401, 403, 404 (auth/permission errors)
- Retryable: Network errors, rate limits, transient failures

#### 2. Parse Repo Activity (`parse_repo_activity`)

**Purpose**: Parses repository and builds knowledge graph.

**Signature**:
```python
@activity.defn
async def parse_repo_activity(input_data: dict) -> dict:
```

**Input**:
```python
{
    "local_path": "/tmp/repo-uuid-abc123",
    "repo_id": "repo-uuid",
    "commit_sha": "abc123..."
}
```

**Output**:
```python
{
    "graph_result": RepoGraphResult(...),
    "stats": {
        "total_symbols": 1500,
        "indexed_files": 200,
        ...
    },
    "repo_id": "repo-uuid",
    "commit_sha": "abc123..."
}
```

**Features**:
- Sends heartbeat for long operations
- Returns graph result and statistics
- Converts stats to dict for serialization

#### 3. Persist Metadata Activity (`persist_metadata_activity`)

**Purpose**: Persists indexing metadata to PostgreSQL.

**Signature**:
```python
@activity.defn
async def persist_metadata_activity(input_data: dict) -> dict:
```

**Input**:
```python
{
    "repo_id": "repo-uuid",
    "commit_sha": "abc123...",
    "parse_result": {
        "graph_result": RepoGraphResult(...),
        "stats": {...}
    }
}
```

**Output**:
```python
{
    "status": "success",
    "snapshot_id": "snapshot-uuid"
}
```

**Implementation**:
- Reconstructs `IndexingStats` from dict
- Calls `MetadataService.persist_indexing_metadata()`
- Returns snapshot ID

#### 4. Persist KG Activity (`persist_kg_activity`)

**Purpose**: Persists knowledge graph to Neo4j.

**Signature**:
```python
@activity.defn
async def persist_kg_activity(input_data: dict) -> dict:
```

**Input**:
```python
{
    "repo_id": "repo-uuid",
    "github_repo_name": "owner/repo",
    "graph_result": RepoGraphResult(...)
}
```

**Output**:
```python
{
    "nodes_created": 1500,
    "nodes_updated": 200,
    "edges_created": 3000,
    "edges_updated": 500
}
```

**Features**:
- Sends heartbeat during persistence
- Returns persistence statistics

#### 5. Cleanup Stale KG Nodes Activity (`cleanup_stale_kg_nodes_activity`)

**Purpose**: Removes stale knowledge graph nodes.

**Signature**:
```python
@activity.defn
async def cleanup_stale_kg_nodes_activity(input_data: dict) -> dict:
```

**Input**:
```python
{
    "repo_id": "repo-uuid",
    "ttl_days": 7  # Optional, default: 30
}
```

**Output**:
```python
{
    "nodes_deleted": 50
}
```

#### 6. Cleanup Repo Activity (`cleanup_repo_activity`)

**Purpose**: Cleans up cloned repository directory.

**Signature**:
```python
@activity.defn
async def cleanup_repo_activity(local_path: str) -> dict:
```

**Input**: `"/tmp/repo-uuid-abc123"`

**Output**:
```python
{
    "status": "cleaned"
}
```

**Error Handling**:
- Logs warnings but doesn't fail workflow
- Ensures cleanup doesn't block workflow completion

### Activity Patterns

#### 1. Service Wrapper Pattern

```python
@activity.defn
async def some_activity(input_data: dict) -> dict:
    # Initialize service
    service = SomeService()
    
    # Call service method
    result = await service.do_work(...)
    
    # Return result
    return result.__dict__  # Convert to dict for serialization
```

#### 2. Error Classification Pattern

```python
try:
    result = await service.do_work(...)
except Exception as e:
    error_msg = str(e).lower()
    
    # Non-retryable errors
    if any(x in error_msg for x in ["401", "403", "404", "unauthorized"]):
        raise ApplicationError(
            f"Non-retryable error: {e}",
            non_retryable=True
        )
    
    # Retryable errors
    raise ApplicationError(f"Retryable error: {e}")
```

#### 3. Heartbeat Pattern

```python
@activity.defn
async def long_running_activity(input_data: dict) -> dict:
    activity.heartbeat("Starting operation")
    
    # Do work in chunks
    for chunk in chunks:
        process_chunk(chunk)
        activity.heartbeat(f"Processed {len(chunks_processed)} chunks")
    
    return result
```

### Activity Context

**Accessing Context**:
```python
ctx = activity.get_current().info
activity.logger.info(f"Activity: {ctx.activity_type}")
activity.logger.info(f"Workflow: {ctx.workflow_id}")
activity.logger.info(f"Run ID: {ctx.workflow_run_id}")
```

**Logging**:
```python
activity.logger.info("Activity started")
activity.logger.error("Activity failed", exc_info=True)
activity.logger.warning("Non-critical issue")
```

### Error Handling

**ApplicationError**:
```python
from temporalio.exceptions import ApplicationError

# Retryable error
raise ApplicationError("Network timeout")

# Non-retryable error
raise ApplicationError(
    "Invalid credentials",
    non_retryable=True
)
```

**Error Types**:
- **Retryable**: Network errors, timeouts, rate limits
- **Non-Retryable**: Auth errors, validation errors, not found

### Serialization

**Dict-Based I/O**:
- Activities receive/return dicts for deterministic serialization
- Complex objects converted to dicts before return
- Stats objects converted via `.__dict__`

**Example**:
```python
# Return complex object as dict
return {
    "graph_result": graph_result,  # RepoGraphResult (dataclass serializes)
    "stats": graph_result.stats.__dict__,  # Convert to dict
}
```

### Service Integration

**No FastAPI Dependencies**:
- Services don't use `Depends(get_db)`
- Services create their own DB sessions
- Compatible with Temporal worker context

**Example**:
```python
# ✅ Good: Service creates own session
service = MetadataService()
result = await service.persist_indexing_metadata(...)

# ❌ Bad: FastAPI dependency injection
service = MetadataService(db=Depends(get_db))  # Won't work!
```

### Testing

```python
# Test activity execution
async def test_clone_repo_activity():
    result = await clone_repo_activity({
        "installation_id": 123,
        "github_repo_name": "test/repo",
        "repo_id": "test-uuid",
        "default_branch": "main",
        "repo_url": "https://github.com/test/repo.git"
    })
    assert "local_path" in result
    assert "commit_sha" in result

# Test error handling
async def test_activity_error_handling():
    with pytest.raises(ApplicationError) as exc:
        await clone_repo_activity(invalid_request)
    assert exc.value.non_retryable == True  # For auth errors
```

### Design Decisions

1. **Thin Wrappers**: Activities are thin wrappers around services
2. **Error Classification**: Distinguish retryable vs non-retryable
3. **Dict Serialization**: Use dicts for deterministic serialization
4. **Heartbeats**: Send heartbeats for long operations
5. **Logging**: Comprehensive logging for debugging

### Dependencies

- **temporalio**: Temporal Python SDK
- **Services**: Business logic from service layer
- **Core**: Database, Neo4j connections

### Configuration

- Task Queue: `repo-indexing-queue` (matches workflow)
- Timeouts: Configured in workflow
- Retry Policies: Configured in workflow

### Future Enhancements

- [ ] Activity timeouts per activity type
- [ ] Custom retry policies per activity
- [ ] Activity cancellation handling
- [ ] Progress tracking via heartbeats
- [ ] Activity result caching
- [ ] Activity metrics/monitoring

