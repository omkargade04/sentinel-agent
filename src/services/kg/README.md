# Knowledge Graph Service Module

## What

The knowledge graph (KG) service module provides high-level business logic and low-level operations for persisting codebase knowledge graphs to Neo4j. It handles node/edge upserts, stale node cleanup, and graph statistics tracking.

## Why

Knowledge graph persistence enables:
- **Code Understanding**: Store structured representation of codebase semantics
- **PR Context Retrieval**: Query affected symbols and relationships for reviews
- **Historical Tracking**: Link symbols across commits using stable IDs
- **Graph Analytics**: Enable complex queries for code analysis

## How

### Architecture

```
services/kg/
├── kg_service.py      # High-level business logic
├── kg_handler.py      # Low-level Neo4j operations
└── README.md         # This file
```

### Key Components

#### 1. KnowledgeGraphService (`kg_service.py`)

**Purpose**: High-level service orchestrating KG persistence operations.

**Key Methods**:

- `persist_kg(repo_id, nodes, edges)`: Persists complete knowledge graph
  ```python
  stats = await service.persist_kg(
      repo_id="repo_uuid",
      nodes=[...],  # List[KnowledgeGraphNode]
      edges=[...]   # List[KnowledgeGraphEdge]
  )
  # Returns: PersistenceStats with created/updated counts
  ```
  
  **Flow**:
  ```
  1. Count existing nodes/edges for repo_id
  2. Batch upsert nodes (via kg_handler.batch_upsert_nodes)
  3. Batch upsert edges (via kg_handler.batch_upsert_edges)
  4. Count final nodes/edges
  5. Calculate created vs updated statistics
  6. Return PersistenceStats
  ```

- `cleanup_stale_nodes(repo_id, ttl_days)`: Removes stale nodes
  ```python
  deleted_count = await service.cleanup_stale_nodes(
      repo_id="repo_uuid",
      ttl_days=30
  )
  # Returns: Number of nodes deleted
  ```
  
  **Flow**:
  ```
  1. Query nodes with last_indexed_at older than TTL
  2. Delete nodes and their relationships (DETACH DELETE)
  3. Return count of deleted nodes
  ```

- `clear_repo_graph(repo_id)`: Nuclear option - delete all repo nodes
  ```python
  deleted_count = await service.clear_repo_graph("repo_uuid")
  # Returns: Number of nodes deleted
  ```

**Statistics Tracking**:
- Tracks nodes_created, nodes_updated, edges_created, edges_updated
- Compares before/after counts to calculate statistics
- Note: Created vs updated is approximate (can't perfectly distinguish)

#### 2. KG Handler (`kg_handler.py`)

**Purpose**: Low-level Neo4j operations using efficient batch patterns.

**Key Functions**:

- `batch_upsert_nodes(driver, nodes, repo_id, database)`: Batch node upsert
  ```python
  await batch_upsert_nodes(
      driver=neo4j_driver,
      nodes=[...],
      repo_id="repo_uuid",
      database="neo4j"
  )
  ```
  
  **Implementation**:
  - Uses `UNWIND` pattern for efficient batch processing
  - Handles FileNode, SymbolNode, TextNode types
  - Uses `MERGE` with `ON CREATE` / `ON MATCH` for idempotency
  - Updates `last_indexed_at` timestamp on all nodes

- `batch_upsert_edges(driver, edges, repo_id, database)`: Batch edge upsert
  ```python
  await batch_upsert_edges(
      driver=neo4j_driver,
      edges=[...],
      repo_id="repo_uuid",
      database="neo4j"
  )
  ```
  
  **Implementation**:
  - Groups edges by type (HAS_SYMBOL, CALLS, etc.)
  - Processes each type in separate batches
  - Uses `MERGE` to create relationships idempotently
  - Links existing nodes via node_id matching

- `cleanup_stale_nodes(driver, repo_id, ttl_days, database)`: Low-level cleanup
  ```python
  deleted_count = await cleanup_stale_nodes(
      driver=neo4j_driver,
      repo_id="repo_uuid",
      ttl_days=30,
      database="neo4j"
  )
  ```

- `init_database(driver, database)`: Initialize Neo4j schema
  ```python
  await init_database(neo4j_driver, database="neo4j")
  ```
  
  **Creates**:
  - Constraints: `node_id` uniqueness, `repo_id` indexes
  - Indexes: On `repo_id`, `relative_path`, `symbol_version_id`, etc.

### Neo4j Schema

**Node Labels**:
- `KGNode`: Base label for all nodes
- `FileNode`: File/directory nodes
- `SymbolNode`: Code symbol nodes (functions, classes, etc.)
- `TextNode`: Text chunk nodes

**Node Properties**:
```cypher
(:KGNode {
    node_id: string,           // Unique node identifier
    repo_id: string,            // Repository identifier
    last_indexed_at: datetime,  // Timestamp for stale cleanup
    // Type-specific properties...
})
```

**Relationship Types**:
- `HAS_FILE`: FileNode → FileNode
- `HAS_SYMBOL`: FileNode → SymbolNode
- `HAS_TEXT`: FileNode → TextNode
- `CONTAINS_SYMBOL`: SymbolNode → SymbolNode
- `CALLS`: SymbolNode → SymbolNode
- `IMPORTS`: FileNode → FileNode/SymbolNode

### Batch Upsert Pattern

**Nodes**:
```cypher
UNWIND $nodes AS node
MERGE (n:KGNode:FileNode {
    node_id: node.node_id,
    repo_id: node.repo_id
})
ON CREATE SET
    n = node.properties,
    n.last_indexed_at = $timestamp
ON MATCH SET
    n.last_indexed_at = $timestamp
```

**Edges**:
```cypher
UNWIND $edges AS edge
MATCH (source:KGNode {
    node_id: edge.source_node_id,
    repo_id: edge.repo_id
})
MATCH (target:KGNode {
    node_id: edge.target_node_id,
    repo_id: edge.repo_id
})
MERGE (source)-[r:HAS_SYMBOL]->(target)
ON CREATE SET r.repo_id = edge.repo_id
ON MATCH SET r.repo_id = edge.repo_id
```

### Stale Node Cleanup

**Query**:
```cypher
MATCH (n:KGNode {repo_id: $repo_id})
WHERE n.last_indexed_at < datetime() - duration({days: $ttl_days})
DETACH DELETE n
RETURN count(n) as deleted_count
```

**Why DETACH DELETE**:
- Removes node and all its relationships
- Prevents orphaned relationships
- Ensures graph consistency

### Usage in Temporal Activities

```python
from src.services.kg import KnowledgeGraphService
from src.core.neo4j import Neo4jConnection
from src.core.config import settings

@activity.defn
async def persist_kg_activity(input_data: dict) -> dict:
    service = KnowledgeGraphService(
        driver=Neo4jConnection.get_driver(),
        database=settings.NEO4J_DATABASE
    )
    
    result = await service.persist_kg(
        repo_id=input_data["repo_id"],
        nodes=input_data["graph_result"].nodes,
        edges=input_data["graph_result"].edges,
    )
    
    return result.__dict__
```

### Error Handling

- **Neo4j Errors**: Wrapped with context in service layer
- **Transaction Failures**: Retry logic handled by Neo4j driver
- **Validation Errors**: Node/edge validation before persistence

### Performance Considerations

1. **Batch Sizes**: Processes nodes/edges in batches (configurable)
2. **Parallel Processing**: Can process multiple repos concurrently
3. **Index Usage**: Proper indexes ensure fast queries
4. **Connection Pooling**: Neo4j driver handles connection pooling

### Dependencies

- **neo4j**: Neo4j Python driver (AsyncDriver)
- **datetime**: For timestamp management
- **logging**: For operation logging

### Configuration

Required settings:
- `NEO4J_URI`: Neo4j connection URI
- `NEO4J_USERNAME`: Neo4j username
- `NEO4J_PASSWORD`: Neo4j password
- `NEO4J_DATABASE`: Database name (default: "neo4j")

### Testing

```python
# Test node persistence
async def test_persist_kg():
    service = KnowledgeGraphService(driver=test_driver, database="test")
    stats = await service.persist_kg(
        repo_id="test_repo",
        nodes=[test_node1, test_node2],
        edges=[test_edge]
    )
    assert stats.nodes_created >= 0
    assert stats.edges_created >= 0

# Test stale cleanup
async def test_cleanup_stale_nodes():
    service = KnowledgeGraphService(driver=test_driver, database="test")
    deleted = await service.cleanup_stale_nodes(
        repo_id="test_repo",
        ttl_days=30
    )
    assert deleted >= 0
```

### Future Enhancements

- [ ] Incremental updates (only changed nodes)
- [ ] Graph versioning for historical queries
- [ ] Relationship weight tracking
- [ ] Graph analytics endpoints
- [ ] Export/import functionality
- [ ] Graph visualization support

