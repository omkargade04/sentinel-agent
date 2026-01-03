# Indexing Service Module

## What

The indexing service module provides core business logic for repository indexing operations. It handles repository cloning, parsing, and metadata persistence - the foundational steps for building a codebase knowledge graph.

## Why

Repository indexing is the first step in enabling AI-powered code review:
- **Codebase Understanding**: Parse and understand repository structure
- **Knowledge Graph Foundation**: Extract symbols and relationships for graph construction
- **Metadata Tracking**: Track indexing history and file metadata
- **Deterministic Processing**: Ensure consistent, reproducible indexing results

## How

### Architecture

```
services/indexing/
├── repo_clone_service.py      # Repository cloning logic
├── repo_parsing_service.py    # Repository parsing orchestration
├── metadata_service.py        # Postgres metadata persistence
└── README.md                 # This file
```

### Key Components

#### 1. RepoCloneService (`repo_clone_service.py`)

**Purpose**: Clones GitHub repositories securely using GitHub App authentication.

**Key Features**:
- **Deterministic Paths**: Uses `/tmp/{repo_id}-{commit_sha}` for consistent locations
- **Atomic Operations**: Temp directory + atomic rename prevents partial clones
- **Shallow Clones**: Uses `--depth 1` for efficiency
- **Commit Resolution**: Resolves branch names to commit SHAs before cloning
- **Concurrency Safe**: Checks for existing clones to avoid duplicate work

**Key Methods**:

- `clone_repo(...)`: Main cloning method
  ```python
  result = await service.clone_repo(
      repo_full_name="owner/repo",
      repo_id="repo_uuid",
      installation_id=12345,
      default_branch="main",
      repo_url="https://github.com/owner/repo.git"
  )
  # Returns: {"local_path": "/tmp/repo_uuid-abc123", "commit_sha": "abc123..."}
  ```

**Flow**:
```
1. Generate installation token via RepositoryHelpers
2. Resolve branch → commit SHA using git ls-remote
3. Check if clone already exists (concurrent execution)
4. Create temp directory: /tmp/{repo_id}-{commit_sha}.tmp-{pid}
5. Git init → Add remote → Shallow fetch → Checkout
6. Atomic rename temp → final path
7. Return local_path and commit_sha
```

**Security**:
- Uses `GIT_ASKPASS` for secure token handling
- Tokens never appear in process list or logs
- Temp files cleaned up on failure

#### 2. RepoParsingService (`repo_parsing_service.py`)

**Purpose**: Orchestrates repository parsing to build knowledge graph representation.

**Key Methods**:

- `parse_repository(...)`: Parses entire repository
  ```python
  graph_result = await service.parse_repository(
      local_path="/tmp/repo_uuid-abc123",
      repo_id="repo_uuid",
      commit_sha="abc123..."
  )
  # Returns: RepoGraphResult with nodes, edges, stats
  ```

**Flow**:
```
1. Validate repository path exists
2. Initialize RepoGraphBuilder with repo_id, commit_sha, repo_root
3. Call builder.build() (synchronous operation)
4. Return RepoGraphResult containing:
   - nodes: List[KnowledgeGraphNode] (FileNode, SymbolNode, TextNode)
   - edges: List[KnowledgeGraphEdge] (HAS_SYMBOL, CALLS, etc.)
   - stats: IndexingStats (file counts, symbol counts, etc.)
```

**Integration**:
- Delegates to `RepoGraphBuilder` from `src/graph/` module
- Uses Tree-sitter parsers via `src/parser/` module
- Returns structured graph data for Neo4j persistence

#### 3. MetadataService (`metadata_service.py`)

**Purpose**: Persists indexing metadata to PostgreSQL for tracking and history.

**Key Methods**:

- `persist_indexing_metadata(...)`: Saves indexing results to database
  ```python
  snapshot_id = await service.persist_indexing_metadata(
      repo_id="repo_uuid",
      commit_sha="abc123...",
      graph_result=RepoGraphResult(...),
      stats=IndexingStats(...)
  )
  # Returns: snapshot_id (UUID string)
  ```

**Database Operations**:

1. **Create RepoSnapshot**: Records indexing event
   ```sql
   INSERT INTO repo_snapshots (id, repository_id, commit_sha, created_at)
   VALUES (snapshot_id, repo_id, commit_sha, NOW())
   ```

2. **Upsert IndexedFiles**: Records all discovered files
   ```sql
   INSERT INTO indexed_files (
       id, repository_id, snapshot_id, file_path, 
       file_sha, language, file_size, line_count, ...
   ) VALUES (...) ON CONFLICT DO UPDATE ...
   ```

3. **Update Repository**: Updates last indexed metadata
   ```sql
   UPDATE repositories 
   SET last_indexed_sha = commit_sha, last_indexed_at = NOW()
   WHERE id = repo_id
   ```

**Transaction Management**:
- Creates own database session (compatible with Temporal activities)
- Proper commit/rollback handling
- Session cleanup in finally block

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│              Repository Indexing Pipeline                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. RepoCloneService.clone_repo()                          │
│     ├── Generate installation token                         │
│     ├── Resolve commit SHA                                  │
│     └── Clone to /tmp/{repo_id}-{commit_sha}               │
│           ↓                                                 │
│  2. RepoParsingService.parse_repository()                  │
│     ├── Initialize RepoGraphBuilder                        │
│     ├── Walk directory tree                                 │
│     ├── Parse files with Tree-sitter                        │
│     ├── Extract symbols (functions, classes, etc.)         │
│     └── Build graph (nodes + edges)                         │
│           ↓                                                 │
│  3. MetadataService.persist_indexing_metadata()             │
│     ├── Create repo_snapshots record                         │
│     ├── Upsert indexed_files records                        │
│     └── Update repositories.last_indexed_*                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Error Handling

**RepoCloneService**:
- `RepoCloneError`: Wrapped exceptions for cloning failures
- Git command failures include stderr output
- Temp directory cleanup on failure

**RepoParsingService**:
- `FileNotFoundError`: Repository path doesn't exist
- Parser errors propagate from RepoGraphBuilder

**MetadataService**:
- Database errors wrapped with context
- Rollback on any failure
- Exception messages include operation context

### Usage in Temporal Activities

These services are designed to work within Temporal activities:

```python
# In indexing_activities.py
@activity.defn
async def clone_repo_activity(repo_request: dict) -> dict:
    service = RepoCloneService()  # No DB dependency needed
    result = await service.clone_repo(...)
    return result

@activity.defn
async def parse_repo_activity(input_data: dict) -> dict:
    service = RepoParsingService()
    graph_result = await service.parse_repository(...)
    return {"graph_result": graph_result, "stats": graph_result.stats.__dict__}

@activity.defn
async def persist_metadata_activity(input_data: dict) -> dict:
    service = MetadataService()  # Creates own DB session
    snapshot_id = await service.persist_indexing_metadata(...)
    return {"status": "success", "snapshot_id": snapshot_id}
```

### Design Decisions

1. **No FastAPI Dependencies**: Services don't use `Depends(get_db)` to work in Temporal
2. **Own Session Management**: MetadataService creates its own DB session
3. **Synchronous Parsing**: RepoGraphBuilder.build() is sync (CPU-bound operation)
4. **Deterministic Paths**: Clone paths include commit SHA for reproducibility
5. **Atomic Cloning**: Temp directory + rename prevents partial clones

### Dependencies

- **asyncio**: For async git operations
- **pathlib**: For path handling
- **shutil**: For directory operations
- **tempfile**: For secure temp file creation
- **SQLAlchemy**: For database operations (MetadataService)
- **RepositoryHelpers**: For GitHub token generation

### Configuration

No specific configuration required - uses:
- System temp directory (`/tmp`)
- Database connection from `SessionLocal`
- GitHub App credentials from `RepositoryHelpers`

### Testing

```python
# Test cloning
async def test_clone_repo():
    service = RepoCloneService()
    result = await service.clone_repo(
        repo_full_name="test/repo",
        repo_id="test-uuid",
        installation_id=123,
        default_branch="main",
        repo_url="https://github.com/test/repo.git"
    )
    assert Path(result["local_path"]).exists()
    assert len(result["commit_sha"]) == 40  # SHA-1 length

# Test parsing
async def test_parse_repository():
    service = RepoParsingService()
    graph_result = await service.parse_repository(
        local_path="/tmp/test-repo-abc123",
        repo_id="test-uuid",
        commit_sha="abc123..."
    )
    assert len(graph_result.nodes) > 0
    assert graph_result.stats.total_files > 0

# Test metadata persistence
async def test_persist_metadata():
    service = MetadataService()
    snapshot_id = await service.persist_indexing_metadata(
        repo_id="test-uuid",
        commit_sha="abc123...",
        graph_result=test_graph_result,
        stats=test_stats
    )
    assert snapshot_id is not None
```

### Future Enhancements

- [ ] Clone caching with TTL
- [ ] Incremental parsing (only changed files)
- [ ] Parallel file parsing for large repos
- [ ] Progress tracking for long-running operations
- [ ] Repository cleanup scheduling

