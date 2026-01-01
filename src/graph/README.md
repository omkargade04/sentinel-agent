# Graph Module

## What

The graph module implements the Knowledge Graph (KG) for the AI Code Reviewer, providing structured 
representation of codebase semantics for context retrieval and PR analysis. It transforms raw source code 
into a queryable graph structure containing files, symbols, relationships, and metadata.

## Why

Knowledge graphs enable:
- **Semantic Code Understanding**: Represent code as structured entities and relationships
- **Efficient Context Retrieval**: Query affected symbols and dependencies for PR reviews
- **Cross-Commit Tracking**: Link symbols across commits using stable identifiers
- **Relationship Analysis**: Understand call graphs, imports, and symbol hierarchies
- **Scalable Storage**: Neo4j provides efficient graph queries and traversal

## How

### Overview

The graph module is responsible for:
1. Defining Knowledge Graph node and edge types
2. Building file-level graphs from parsed code
3. Constructing repository-wide graphs
4. Generating stable symbol identifiers for cross-commit linking
5. Providing utilities for ID generation and graph operations

### Architecture

```
graph/
├── __init__.py              # Module exports
├── graph_types.py           # Node/edge type definitions and Neo4j mappings
├── repo_graph_builder.py   # Repository-wide KG construction (main orchestrator)
├── file_graph_builder.py    # Single-file KG construction
├── knowledge_graph.py       # Legacy module (conceptual documentation)
├── utils.py                 # ID generation utilities
├── constants.py             # Default exclusion lists
└── README.md                # This file
```

### Key Components

#### 1. RepoGraphBuilder (`repo_graph_builder.py`)

**Purpose**: Main orchestrator that builds complete knowledge graphs for entire repositories.

**Key Features**:
- Walks directory tree recursively
- Creates FileNode hierarchy for directory structure
- Delegates file processing to FileGraphBuilder
- Handles large files with chunked extraction
- Tracks indexing statistics
- Excludes build/cache directories

**Key Methods**:

- `build()`: Builds complete repository graph
  ```python
  builder = RepoGraphBuilder(
      repo_id="repo-uuid",
      commit_sha="abc123...",
      repo_root=Path("/path/to/repo")
  )
  result = builder.build()
  # Returns: RepoGraphResult with nodes, edges, stats
  ```

**Configuration**:
- `max_file_size_bytes`: 1MB default (uses chunked extraction above this)
- `max_absolute_file_size_bytes`: 10MB hard limit (skips files above this)
- `max_symbols_per_file`: 500 default
- `excluded_dirs`: Build/cache directories (node_modules, __pycache__, etc.)
- `excluded_files`: Lock files (package-lock.json, etc.)

**Flow**:
```
1. Create root FileNode for repository root
2. Walk directory tree recursively
3. For each directory:
   ├── Create FileNode
   └── Create HAS_FILE edge to parent
4. For each file:
   ├── Check if excluded (size, name, directory)
   ├── Create FileNode
   ├── Create HAS_FILE edge to parent directory
   └── Delegate to FileGraphBuilder for content processing
5. Aggregate all nodes and edges
6. Return RepoGraphResult
```

#### 2. FileGraphBuilder (`file_graph_builder.py`)

**Purpose**: Builds knowledge graph subgraphs for individual files.

**Key Methods**:

- `build_file_graph(...)`: Processes a single file
  ```python
  builder = FileGraphBuilder(
      repo_id="repo-uuid",
      commit_sha="abc123...",
      max_symbols=500,
      chunk_size=1000,
      chunk_overlap=200
  )
  
  next_id, nodes, edges = builder.build_file_graph(
      parent_node=parent_kg_node,
      file_path=Path("src/main.py"),
      next_node_id=100
  )
  ```

**File Type Detection**:
- **Code Files**: Uses Tree-sitter parser (Python, JavaScript, etc.)
- **Text Files**: Chunks markdown/text files (`.md`, `.txt`, `.rst`)

**Code File Processing**:
```
1. Parse file with Tree-sitter → AST
2. Get language-specific extractor
3. Extract symbols (functions, classes, methods)
4. Generate symbol IDs (version + stable)
5. Build symbol hierarchy (parent-child relationships)
6. Create SymbolNodes and edges:
   ├── HAS_SYMBOL: FileNode → SymbolNode
   ├── CONTAINS_SYMBOL: SymbolNode → SymbolNode (nesting)
   └── CALLS: SymbolNode → SymbolNode (best-effort)
```

**Text File Processing**:
```
1. Read file content
2. Chunk text into overlapping segments
3. Create TextNodes for each chunk
4. Create edges:
   ├── HAS_TEXT: FileNode → TextNode
   └── NEXT_CHUNK: TextNode → TextNode (sequential)
```

#### 3. Graph Types (`graph_types.py`)

**Purpose**: Defines data models for nodes and edges with Neo4j serialization.

**Node Types**:

- **FileNode**: Represents files/directories
  ```python
  FileNode(
      basename="main.py",
      relative_path="src/main.py"
  )
  ```

- **SymbolNode**: Represents code symbols
  ```python
  SymbolNode(
      symbol_version_id="sha256...",
      stable_symbol_id="sha256...",
      kind="function",
      name="process_data",
      qualified_name="main.process_data",
      language="python",
      relative_path="src/main.py",
      start_line=10,
      end_line=25,
      signature="def process_data(data: str) -> dict:",
      docstring="Process input data...",
      fingerprint="sha256..."
  )
  ```

- **TextNode**: Represents text chunks
  ```python
  TextNode(
      text="This is a documentation chunk...",
      start_line=0,
      end_line=50
  )
  ```

**Edge Types** (`KnowledgeGraphEdgeType` enum):
- `HAS_FILE`: FileNode → FileNode (directory structure)
- `HAS_SYMBOL`: FileNode → SymbolNode (file contains symbol)
- `HAS_TEXT`: FileNode → TextNode (file contains text)
- `NEXT_CHUNK`: TextNode → TextNode (sequential chunks)
- `CONTAINS_SYMBOL`: SymbolNode → SymbolNode (nesting)
- `CALLS`: SymbolNode → SymbolNode (function calls)
- `IMPORTS`: FileNode → FileNode/SymbolNode (imports)
- `DEFINES`: FileNode → SymbolNode (definition relationship)

**Neo4j Serialization**:
```python
kg_node = KnowledgeGraphNode(
    node_id="node_1",
    node=FileNode(...)
)
neo4j_node = kg_node.to_neo4j_node()
# Returns TypedDict ready for Neo4j upsert
```

#### 4. Utils (`utils.py`)

**Purpose**: ID generation utilities for symbol identity management.

**Key Functions**:

- `generate_symbol_version_id(...)`: Snapshot-scoped ID
  ```python
  version_id = generate_symbol_version_id(
      commit_sha="abc123...",
      relative_path="src/main.py",
      kind="function",
      name="process_data",
      qualified_name="main.process_data",
      start_line=10,
      end_line=25
  )
  # Returns: SHA256 hash of canonical string
  ```

- `generate_stable_symbol_id(...)`: Cross-snapshot stable ID
  ```python
  stable_id = generate_stable_symbol_id(
      repo_id="repo-uuid",
      kind="function",
      qualified_name="main.process_data",
      name="process_data",
      fingerprint="sha256..."  # Optional, preferred
  )
  ```

- `generate_ast_fingerprint_from_types(...)`: AST fingerprint
  ```python
  fingerprint = generate_ast_fingerprint_from_types([
      "function_definition",
      "identifier",
      "parameters",
      "block"
  ])
  ```

#### 5. Constants (`constants.py`)

**Purpose**: Default exclusion lists for repository indexing.

**DEFAULT_EXCLUDED_DIRS**: Build/cache directories
- `.git`, `__pycache__`, `node_modules`, `dist`, `build`, etc.

**DEFAULT_EXCLUDED_FILES**: Lock/config files
- `package-lock.json`, `yarn.lock`, `Pipfile.lock`, etc.

**Usage**:
```python
from src.graph.constants import DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_FILES

builder = RepoGraphBuilder(
    repo_id="repo-uuid",
    commit_sha="abc123...",
    repo_root=Path("/path/to/repo"),
    excluded_dirs=DEFAULT_EXCLUDED_DIRS,  # Optional override
    excluded_files=DEFAULT_EXCLUDED_FILES  # Optional override
)
```

### Integration with Other Modules

**With Parser Module** (`src/parser/`):
- Uses `tree_sitter_parser` for AST parsing
- Uses `extractor` module for symbol extraction
- Language-specific extractors handle symbol extraction

**With Indexing Service** (`src/services/indexing/`):
- `RepoParsingService` uses `RepoGraphBuilder` to build graphs
- Graph results passed to KG persistence service

**With KG Service** (`src/services/kg/`):
- Graph nodes/edges persisted to Neo4j via `KnowledgeGraphService`
- Uses `to_neo4j_node()` for serialization

## Knowledge Graph Model

### Node Types

| Node Type | Description | Use Case |
|-----------|-------------|----------|
| `FileNode` | Represents a file or directory | File tree navigation, path-based queries |
| `SymbolNode` | Represents a code symbol (function, class, method) | Semantic analysis, call graphs |
| `TextNode` | Represents a text chunk | Documentation, non-code content |

**Note:** Raw AST nodes are NOT stored. Tree-sitter ASTs are used ephemerally during 
extraction to create higher-level `SymbolNode` objects.

### Edge Types

| Edge Type | Source → Target | Description |
|-----------|-----------------|-------------|
| `HAS_FILE` | FileNode → FileNode | Directory contains file |
| `HAS_SYMBOL` | FileNode → SymbolNode | File defines symbol |
| `HAS_TEXT` | FileNode → TextNode | File contains text chunk |
| `NEXT_CHUNK` | TextNode → TextNode | Sequential text chunks |
| `CONTAINS_SYMBOL` | SymbolNode → SymbolNode | Symbol nesting (class contains method) |
| `CALLS` | SymbolNode → SymbolNode | Function call relationship |
| `IMPORTS` | FileNode → FileNode/SymbolNode | Import dependency |
| `DEFINES` | FileNode → SymbolNode | Definition relationship |

### Usage Examples

**Building Repository Graph**:
```python
from src.graph.repo_graph_builder import RepoGraphBuilder
from pathlib import Path

# Initialize builder
builder = RepoGraphBuilder(
    repo_id="my-repo-123",
    commit_sha="abc123def456",
    repo_root=Path("/path/to/repo"),
    max_file_size_bytes=1_000_000,  # 1MB
    max_symbols_per_file=500
)

# Build graph
result = builder.build()

# Access results
print(f"Total nodes: {len(result.nodes)}")
print(f"Total edges: {len(result.edges)}")
print(f"Files indexed: {result.stats.indexed_files}")
print(f"Symbols extracted: {result.stats.total_symbols}")

# Filter nodes by type
file_nodes = [n for n in result.nodes if isinstance(n.node, FileNode)]
symbol_nodes = [n for n in result.nodes if isinstance(n.node, SymbolNode)]
```

**Building File Graph**:
```python
from src.graph.file_graph_builder import FileGraphBuilder
from src.graph.graph_types import KnowledgeGraphNode, FileNode
from pathlib import Path

# Initialize builder
builder = FileGraphBuilder(
    repo_id="repo-uuid",
    commit_sha="abc123...",
    max_symbols=500
)

# Create parent node
parent = KnowledgeGraphNode(
    node_id="parent_1",
    node=FileNode(basename="src", relative_path="src")
)

# Build file graph
next_id, nodes, edges = builder.build_file_graph(
    parent_node=parent,
    file_path=Path("src/main.py"),
    next_node_id=100
)

# Process results
for node in nodes:
    if isinstance(node.node, SymbolNode):
        print(f"Symbol: {node.node.name} ({node.node.kind})")
```

**ID Generation**:
```python
from src.graph.utils import (
    generate_symbol_version_id,
    generate_stable_symbol_id,
    generate_ast_fingerprint_from_types
)

# Version ID (snapshot-scoped)
version_id = generate_symbol_version_id(
    commit_sha="abc123...",
    relative_path="src/main.py",
    kind="function",
    name="process_data",
    qualified_name="main.process_data",
    start_line=10,
    end_line=25
)

# Stable ID (cross-snapshot)
fingerprint = generate_ast_fingerprint_from_types([
    "function_definition", "identifier", "parameters"
])
stable_id = generate_stable_symbol_id(
    repo_id="repo-uuid",
    kind="function",
    qualified_name="main.process_data",
    name="process_data",
    fingerprint=fingerprint
)
```

## Symbol Identity System

The graph module implements a dual-ID system for robust symbol tracking:

### symbol_version_id (Snapshot-Scoped)

- **Purpose:** Identify a symbol within a specific commit
- **Components:** commit_sha, path, kind, name, start_line, end_line
- **Use Cases:**
  - PR hunk → symbol mapping
  - Inline comment anchoring
  - Deterministic upserts

### stable_symbol_id (Cross-Snapshot)

- **Purpose:** Track the same logical symbol across commits
- **Components:** repo_id, kind, fingerprint (or qualified_name fallback)
- **Use Cases:**
  - Historical symbol linking
  - Call graph continuity
  - Rename/move tolerance

### Fingerprinting

AST-based fingerprinting creates stable identities by hashing the tree structure:

```python
# AST node types for a function
node_types = ["function_definition", "name", "parameters", "body", "return_statement"]

# Fingerprint is stable across whitespace/formatting changes
fingerprint = generate_ast_fingerprint_from_types(node_types)
```

## Graph Construction Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Repository Indexing Flow                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   1. Clone/Fetch Repository                                         │
│            ↓                                                        │
│   2. Walk Directory Tree → Create FileNode hierarchy                │
│            ↓                                                        │
│   3. For Each Code File:                                            │
│      ├── Parse with Tree-sitter → Ephemeral AST                    │
│      ├── Extract symbols → SymbolNode list                          │
│      ├── Build hierarchy → CONTAINS_SYMBOL edges                    │
│      ├── Generate IDs (version + stable)                            │
│      └── Create HAS_SYMBOL edges                                    │
│            ↓                                                        │
│   4. For Each Text File:                                            │
│      ├── Chunk content → TextNode list                              │
│      └── Create HAS_TEXT + NEXT_CHUNK edges                         │
│            ↓                                                        │
│   5. Persist to Neo4j                                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## PR Review Context Retrieval

The KG enables efficient context retrieval for PR reviews:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PR Review Context Flow                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   1. Parse PR Diff → Changed line ranges per file                   │
│            ↓                                                        │
│   2. Map hunks to SymbolNodes (interval query on spans)             │
│            ↓                                                        │
│   3. Build Seed Set S from affected symbols                         │
│            ↓                                                        │
│   4. Expand context via graph traversal:                            │
│      ├── CALLS edges → Find callers/callees                         │
│      ├── CONTAINS_SYMBOL → Find parent/child symbols                │
│      └── IMPORTS → Find dependencies                                │
│            ↓                                                        │
│   5. Vector similarity search (pgvector) on embeddings              │
│            ↓                                                        │
│   6. Assemble token-bounded Context Pack for LLM                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Neo4j Integration

### Schema

```cypher
// Node labels
(:FileNode {node_id, basename, relative_path})
(:SymbolNode {
    node_id,
    symbol_version_id,
    stable_symbol_id,
    kind, name, qualified_name,
    language, relative_path,
    start_line, end_line,
    signature, docstring, fingerprint
})
(:TextNode {node_id, text, start_line, end_line})

// Edge types
(:FileNode)-[:HAS_FILE]->(:FileNode)
(:FileNode)-[:HAS_SYMBOL]->(:SymbolNode)
(:FileNode)-[:HAS_TEXT]->(:TextNode)
(:TextNode)-[:NEXT_CHUNK]->(:TextNode)
(:SymbolNode)-[:CONTAINS_SYMBOL]->(:SymbolNode)
(:SymbolNode)-[:CALLS]->(:SymbolNode)
(:FileNode)-[:IMPORTS]->(:FileNode|:SymbolNode)
```

### Sample Queries

```cypher
// Find all functions in a file
MATCH (f:FileNode {relative_path: 'src/main.py'})-[:HAS_SYMBOL]->(s:SymbolNode)
WHERE s.kind = 'function'
RETURN s

// Find symbols affected by changed lines
MATCH (s:SymbolNode {relative_path: $file_path})
WHERE s.start_line <= $end_line AND s.end_line >= $start_line
RETURN s ORDER BY (s.end_line - s.start_line) ASC LIMIT 1

// Find callers of a function
MATCH (caller:SymbolNode)-[:CALLS]->(target:SymbolNode {name: 'process_data'})
RETURN caller

// Find nested symbols (class with methods)
MATCH (parent:SymbolNode {kind: 'class'})-[:CONTAINS_SYMBOL]->(child:SymbolNode)
WHERE parent.name = 'MyClass'
RETURN child
```

### Error Handling

**File Processing Errors**:
- `FileNotFoundError`: File doesn't exist
- `RuntimeError`: File read failures
- `UnsupportedLanguageError`: Language not supported by Tree-sitter
- `ParseError`: Tree-sitter parsing failures

**Error Handling Strategy**:
- Large files (>10MB) are skipped silently
- Parse errors are logged but don't stop indexing
- Statistics track failed/skipped files
- Graph building continues despite individual file failures

**Example**:
```python
try:
    result = builder.build()
except FileNotFoundError as e:
    logger.error(f"Repository not found: {e}")
    raise
except Exception as e:
    logger.error(f"Graph building failed: {e}")
    # Check result.stats.errors for detailed error list
    raise
```

### Design Decisions

1. **Ephemeral ASTs**: Tree-sitter ASTs not stored, only extracted symbols
2. **Dual ID System**: Version IDs for snapshot scoping, stable IDs for cross-commit tracking
3. **Chunked Processing**: Large files processed in batches to manage memory
4. **Exclusion Lists**: Common build/cache directories excluded by default
5. **Statistics Tracking**: Comprehensive stats for monitoring and debugging
6. **Fault Tolerance**: Individual file failures don't stop entire indexing

### Performance Considerations

**Memory Management**:
- Large files use chunked extraction
- Garbage collection triggered periodically
- Nodes/edges accumulated in memory (consider streaming for very large repos)

**Processing Speed**:
- Parallel file processing possible (future enhancement)
- Tree-sitter parsing is fast (C-based)
- Symbol extraction is CPU-bound

**Scalability**:
- Handles repositories with thousands of files
- Memory usage scales with repository size
- Consider incremental updates for large repos

### Testing

**Unit Tests**:
```bash
# Run graph tests
pytest tests/graph/ -v

# Test specific component
pytest tests/graph/test_repo_graph_builder.py -v
pytest tests/graph/test_file_graph_builder.py -v
pytest tests/graph/test_graph_types.py -v
pytest tests/graph/test_utils.py -v
```

**Integration Test**:
```python
# Test repository graph building
from src.graph.repo_graph_builder import RepoGraphBuilder
from pathlib import Path

def test_repo_graph_building():
    builder = RepoGraphBuilder(
        repo_id="test-repo",
        commit_sha="test-commit",
        repo_root=Path("test_repo")
    )
    result = builder.build()
    
    assert len(result.nodes) > 0
    assert len(result.edges) > 0
    assert result.stats.indexed_files > 0
    assert result.root_node is not None
```

**Manual Testing**:
```python
# Test file graph building
from src.graph.file_graph_builder import FileGraphBuilder
from src.graph.graph_types import KnowledgeGraphNode, FileNode
from pathlib import Path

builder = FileGraphBuilder(
    repo_id="test-repo",
    commit_sha="test-commit"
)
parent = KnowledgeGraphNode(
    node_id="root",
    node=FileNode(basename="src", relative_path="src")
)
next_id, nodes, edges = builder.build_file_graph(
    Path("src/example.py"),
    parent,
    next_node_id=1
)
print(f"Nodes: {len(nodes)}, Edges: {len(edges)}")
for n in nodes:
    print(f"  {type(n.node).__name__}: {n.node_id}")
```

### Dependencies

- **pathlib**: Path handling
- **tree-sitter**: AST parsing (via parser module)
- **hashlib**: ID generation
- **dataclasses**: Data models
- **typing**: Type hints
- **logging**: Operation logging

### Configuration

**Environment Variables**: None required (uses defaults)

**Builder Configuration**:
- File size limits: Configurable via constructor
- Exclusion lists: Configurable via constructor
- Symbol limits: Configurable per file

### Future Enhancements

- [ ] Incremental graph updates (only changed files)
- [ ] Parallel file processing
- [ ] Streaming graph construction for very large repos
- [ ] Graph diff computation
- [ ] Symbol rename detection
- [ ] Call graph accuracy improvements
- [ ] Import resolution improvements
- [ ] Graph visualization utilities

## References

- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [Cypher Query Language](https://neo4j.com/developer/cypher/)
- [Knowledge Graphs for Code](https://arxiv.org/abs/2104.05310)
