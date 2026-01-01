"""Knowledge Graph persistence module.

This module provides both low-level Neo4j operations (handler) and high-level
business logic (service) for persisting knowledge graphs to Neo4j.

Public API:
  - KnowledgeGraphService: High-level service for KG persistence
  - init_database: Initialize Neo4j constraints and indexes
  - batch_upsert_nodes: Low-level batch node upsert
  - batch_upsert_edges: Low-level batch edge upsert
  - cleanup_stale_nodes: Low-level cleanup of stale nodes
"""

from src.services.kg.kg_handler import (
    batch_upsert_edges,
    batch_upsert_nodes,
    cleanup_stale_nodes,
    init_database,
)
from src.services.kg.kg_service import KnowledgeGraphService

__all__ = [
    "KnowledgeGraphService",
    "init_database",
    "batch_upsert_nodes",
    "batch_upsert_edges",
    "cleanup_stale_nodes",
]
