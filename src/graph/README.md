# Graph Module

This module implements the Knowledge Graph (KG) for the AI Code Reviewer, providing structured 
representation of codebase semantics for context retrieval and PR analysis.

## Overview

The graph module is responsible for:
1. Defining Knowledge Graph node and edge types
2. Building file-level graphs from parsed code
3. Managing Neo4j persistence and queries
4. Generating stable symbol identifiers for cross-commit linking

## Architecture

```
graph/
├── __init__.py           # Module exports
├── graph_types.py        # Node/edge type definitions and Neo4j mappings
├── file_graph_builder.py # Single-file KG construction
├── knowledge_graph.py    # Repository-wide KG orchestration
├── utils.py              # ID generation utilities
├── symbol_extractor.py   # (deprecated, use src/parser/symbol_extractor.py)
└── README.md             # This file
```

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

## Key Components

### Graph Types (`graph_types.py`)

Defines data models for nodes and edges with Neo4j serialization:

```python
from src.graph.graph_types import (
    FileNode,
    SymbolNode,
    TextNode,
    KnowledgeGraphNode,
    KnowledgeGraphEdge,
    KnowledgeGraphEdgeType,
)

# Create a file node
file_node = FileNode(basename="example.py", relative_path="src/example.py")

# Wrap in KG node with ID
kg_node = KnowledgeGraphNode(node_id="node_1", node=file_node)

# Convert to Neo4j format
neo4j_node = kg_node.to_neo4j_node()
```

### File Graph Builder (`file_graph_builder.py`)

Constructs KG subgraphs for individual files:

```python
from src.graph.file_graph_builder import FileGraphBuilder

builder = FileGraphBuilder(
    root_path=Path("/path/to/repo"),
    max_ast_depth=5,
    text_chunk_size=500,
    text_chunk_overlap=50,
)

# Build graph for a file
next_id, nodes, edges = builder.build_file_graph(
    file_path=Path("/path/to/repo/src/main.py"),
    parent_node=parent_kg_node,
    next_node_id=100,
    commit_sha="abc123",
    repo_id="repo_uuid",
)
```

The builder automatically:
- Detects file type (code vs text)
- Parses code files with Tree-sitter
- Extracts symbols using language-specific extractors
- Chunks text files for documentation search

### Utils (`utils.py`)

ID generation utilities for symbol identity management:

```python
from src.graph.utils import (
    generate_symbol_version_id,
    generate_stable_symbol_id,
    generate_ast_fingerprint_from_types,
)

# Snapshot-scoped ID (changes with line numbers)
version_id = generate_symbol_version_id(
    commit_sha="abc123",
    relative_path="src/main.py",
    kind="function",
    name="process_data",
    qualified_name="main.process_data",
    start_line=10,
    end_line=25,
)

# Cross-snapshot stable ID (resilient to refactors)
stable_id = generate_stable_symbol_id(
    repo_id="repo_uuid",
    kind="function",
    qualified_name="main.process_data",
    name="process_data",
    fingerprint="sha256_of_ast_types",
)

# Generate fingerprint from AST node types
fingerprint = generate_ast_fingerprint_from_types([
    "function_definition", "identifier", "parameters", "block"
])
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

## Error Handling

The module defines specific exceptions for robust error handling:

- File read errors raise `FileNotFoundError` or `RuntimeError`
- Unsupported languages raise `UnsupportedLanguageError`
- Parse failures raise `ParseError`

## Testing

```bash
# Run graph tests
pytest tests/graph/ -v

# Test graph building for a file
python -c "
from src.graph.file_graph_builder import FileGraphBuilder
from src.graph.graph_types import KnowledgeGraphNode, FileNode
from pathlib import Path

builder = FileGraphBuilder(root_path=Path('.'))
parent = KnowledgeGraphNode(
    node_id='root',
    node=FileNode(basename='src', relative_path='src')
)
next_id, nodes, edges = builder.build_file_graph(
    Path('src/example.py'),
    parent,
    next_node_id=1,
    commit_sha='test',
    repo_id='test_repo'
)
print(f'Nodes: {len(nodes)}, Edges: {len(edges)}')
for n in nodes:
    print(f'  {type(n.node).__name__}: {n.node_id}')
"
```

## References

- [Neo4j Python Driver](https://neo4j.com/docs/python-manual/current/)
- [Cypher Query Language](https://neo4j.com/developer/cypher/)
- [Knowledge Graphs for Code](https://arxiv.org/abs/2104.05310)
