"""
KG Candidate Retriever

Orchestrates Neo4j KG queries to retrieve bounded context candidates
for PR review. Converts SeedSetS0 into KG candidate sets with drift metadata.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.models.schemas.pr_review.seed_set import SeedSetS0, SeedSymbol
from src.services.kg.kg_query_service import KGQueryService
from src.core.pr_review_config import pr_review_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class KGCandidateStats:
    """" Statistics from KG candidate retrieval. """
    seed_symbols_processed: int = 0
    seed_files_processed: int = 0
    kg_symbols_found: int = 0
    kg_symbols_missing: int = 0
    callers_retrieved: int = 0
    callees_retrieved: int = 0
    contains_retrieved: int = 0
    import_neighbors_retrieved: int = 0
    docs_retrieved: int = 0
    total_candidates: int = 0
    retrieval_duration_ms: int = 0
    
    
@dataclass
class KGCandidateResult:
    """Result of KG candidate retrieval."""
    kg_commit_sha: Optional[str] = None
    symbol_matches: List[Dict[str, Any]] = field(default_factory=list)
    neighbors: List[Dict[str, Any]] = field(default_factory=list)
    import_neighbors: List[Dict[str, Any]] = field(default_factory=list)
    docs: List[Dict[str, Any]] = field(default_factory=list)
    stats: KGCandidateStats = field(default_factory=KGCandidateStats)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "kg_commit_sha": self.kg_commit_sha,
            "symbol_matches": self.symbol_matches,
            "neighbors": self.neighbors,
            "import_neighbors": self.import_neighbors,
            "docs": self.docs,
            "stats": {
                "seed_symbols_processed": self.stats.seed_symbols_processed,
                "seed_files_processed": self.stats.seed_files_processed,
                "kg_symbols_found": self.stats.kg_symbols_found,
                "kg_symbols_missing": self.stats.kg_symbols_missing,
                "callers_retrieved": self.stats.callers_retrieved,
                "callees_retrieved": self.stats.callees_retrieved,
                "contains_retrieved": self.stats.contains_retrieved,
                "import_neighbors_retrieved": self.stats.import_neighbors_retrieved,
                "docs_retrieved": self.stats.docs_retrieved,
                "total_candidates": self.stats.total_candidates,
                "retrieval_duration_ms": self.stats.retrieval_duration_ms,
            },
            "warnings": self.warnings,
        }
        
class KGCandidateRetriever:
    """
    Retrieves bounded KG context candidates from Neo4j for PR review.

    Responsibilities:
    - Convert SeedSetS0 symbols/files → KG queries
    - Apply hard limits at each stage
    - Deduplicate candidates across seeds
    - Track drift (kg_commit_sha) and missing symbols
    - Graceful degradation on Neo4j failures

    Usage:
        retriever = KGCandidateRetriever(kg_service)
        result = await retriever.retrieve_candidates(repo_id, seed_set)
    """
    # Default doc path prefixes to search
    DOC_PATH_PREFIXES = ("README", "docs/", "doc/", "documentation/")

    def __init__(self, kg_service: KGQueryService):
        self._kg = kg_service
        self._limits = pr_review_settings.limits
        
    async def retrieve_candidates(
        self,
        repo_id: str,
        seed_set: SeedSetS0,
    ) -> KGCandidateResult:
        """
            Retrieve all KG candidates for a seed set with strict bounding.

            Args:
                repo_id: Repository UUID string
                seed_set: Seed symbols and files from PR AST analysis

            Returns:
                KGCandidateResult with bounded candidates + stats + warnings
        """
        start_time = time.time()
        result = KGCandidateResult()
        
        # Early exit if no seeds
        if not seed_set.seed_symbols and not seed_set.seed_files:
            logger.info(f"No seeds for repo {repo_id}, skipping KG retrieval")
            return result
        
        try:
            # 1. Get KG commit SHA (for drift detection)
            result.kg_commit_sha = await self._kg.get_repo_commit_sha(repo_id)
            if result.kg_commit_sha:
                logger.debug(f"KG commit SHA for repo {repo_id}: {result.kg_commit_sha[:8]}")
            else:
                result.warnings.append("kg_commit_sha_not_found")
                logger.warning(f"No commit SHA found in KG for repo {repo_id}")
                
            # Track seen node_ids for deduplication
            seen_node_ids: Set[str] = set()
            
            # 2. Process seed symbols → symbol matches + neighbors
            await self._process_seed_symbols(
                repo_id, seed_set.seed_symbols, result, seen_node_ids
            )
            
            # 3. Process seed files → import neighborhood
            await self._process_seed_files(
                repo_id, seed_set, result, seen_node_ids
            )
            
            # 4. Retrieve documentation context
            await self._retrieve_docs(repo_id, result, seen_node_ids)
            
            # 5. Calculate totals
            result.stats.total_candidates = (
                len(result.symbol_matches)
                + len(result.neighbors)
                + len(result.import_neighbors)
                + len(result.docs)
            )
        except Exception as e:
            logger.error(f"KG candidate retrieval failed for repo {repo_id}: {e}", exc_info=True)
            result.warnings.append(f"kg_retrieval_error: {type(e).__name__}")
            # Graceful degradation: return partial results collected so far
        finally:
            result.stats.retrieval_duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                f"KG candidate retrieval for repo {repo_id}: "
                f"{result.stats.total_candidates} candidates in {result.stats.retrieval_duration_ms}ms"
            )

        return result
    
    async def _process_seed_symbols(
        self,
        repo_id: str,
        seed_symbols: List[SeedSymbol],
        result: KGCandidateResult,
        seen_node_ids: Set[str],
    ) -> None:
        """
        Process seed symbols to find KG symbol matches and neighbors.
        """
        max_matches_per_seed = getattr(self._limits, "max_kg_symbol_matches_per_seed", 5)
        max_callers = self._limits.max_callers_per_seed
        max_callees = self._limits.max_callees_per_seed
        
        for seed in seed_symbols:
            result.stats.seed_symbols_processed += 1
            
            # Find KG symbol matches
            matches = await self._kg.find_symbol(
                repo_id=repo_id,
                file_path=seed.file_path,
                name=seed.name,
                kind=seed.kind.value if hasattr(seed.kind, "value") else seed.kind,
                qualified_name=seed.qualified_name,
                fingerprint=seed.fingerprint,
                limit=max_matches_per_seed,
            )
            
            if not matches:
                result.stats.kg_symbols_missing += 1
                logger.debug(
                    f"No KG match for seed symbol: {seed.file_path}:{seed.name}"
                )
                continue
            
            # Track matches (dedupe by node_id)
            for match in matches:
                node_id = match.get("node_id")
                if node_id and node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    result.symbol_matches.append({
                        "seed_symbol": {
                            "file_path": seed.file_path,
                            "name": seed.name,
                            "kind": seed.kind.value if hasattr(seed.kind, "value") else seed.kind,
                            "qualified_name": seed.qualified_name,
                        },
                        "kg_symbol": match,
                    })
                    result.stats.kg_symbols_found += 1

                    # Expand neighbors for this matched symbol
                    await self._expand_symbol_neighbors(
                        repo_id, node_id, max_callers, max_callees,
                        result, seen_node_ids
                    )
                    
    async def _expand_symbol_neighbors(
        self,
        repo_id: str,
        symbol_node_id: str,
        max_callers: int,
        max_callees: int,
        result: KGCandidateResult,
        seen_node_ids: Set[str],
    ) -> None:
        """Expand callers, callees, and contains for a matched symbol."""
        
        # Callers (incoming CALLS)
        callers = await self._kg.expand_symbol_neighbors(
            repo_id=repo_id,
            symbol_node_id=symbol_node_id,
            rel_types=["CALLS"],
            direction="incoming",
            limit=max_callers,
        )
        
        for neighbor in callers:
            node_id = neighbor.get("node", {}).get("node_id")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                result.neighbors.append({
                    "relationship": "caller",
                    "source_symbol_id": symbol_node_id,
                    **neighbor,
                })
                result.stats.callers_retrieved += 1
                
        # Callees (outgoing CALLS)
        callees = await self._kg.expand_symbol_neighbors(
            repo_id=repo_id,
            symbol_node_id=symbol_node_id,
            rel_types=["CALLS"],
            direction="outgoing",
            limit=max_callees,
        )
        
        for neighbor in callees:
            node_id = neighbor.get("node", {}).get("node_id")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                result.neighbors.append({
                    "relationship": "callee",
                    "source_symbol_id": symbol_node_id,
                    **neighbor,
                })
                result.stats.callees_retrieved += 1
                
        # Contains (outgoing CONTAINS_SYMBOL) - nested symbols
        contains_limit = getattr(self._limits, "max_contains_per_seed", 5)
        contains = await self._kg.expand_symbol_neighbors(
            repo_id=repo_id,
            symbol_node_id=symbol_node_id,
            rel_types=["CONTAINS_SYMBOL"],
            direction="outgoing",
            limit=contains_limit,
        )
        for neighbor in contains:
            node_id = neighbor.get("node", {}).get("node_id")
            if node_id and node_id not in seen_node_ids:
                seen_node_ids.add(node_id)
                result.neighbors.append({
                    "relationship": "contains",
                    "source_symbol_id": symbol_node_id,
                    **neighbor,
                })
                result.stats.contains_retrieved += 1

    async def _process_seed_files(
        self,
        repo_id: str,
        seed_set: SeedSetS0,
        result: KGCandidateResult,
        seen_node_ids: Set[str],
    ) -> None:
        """
        Process files for import neighborhood.
        Includes both seed_files AND unique files from seed_symbols.
        """
        max_imports_per_file = getattr(
            self._limits, "max_import_files_per_seed_file", 10
        )
        
        # Collect unique file paths from both sources
        file_paths: Set[str] = set()
        for sf in seed_set.seed_files:
            file_paths.add(sf.file_path)
        for ss in seed_set.seed_symbols:
            file_paths.add(ss.file_path)

        for file_path in file_paths:
            result.stats.seed_files_processed += 1

            # Outgoing imports (what this file imports)
            outgoing = await self._kg.get_import_neighborhood(
                repo_id=repo_id,
                file_path=file_path,
                direction="outgoing",
                limit=max_imports_per_file,
            )
            for neighbor in outgoing:
                node_id = neighbor.get("node", {}).get("node_id")
                if node_id and node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    result.import_neighbors.append({
                        "relationship": "imports",
                        "source_file": file_path,
                        **neighbor,
                    })
                    result.stats.import_neighbors_retrieved += 1

            # Incoming imports (what imports this file) - limited
            incoming = await self._kg.get_import_neighborhood(
                repo_id=repo_id,
                file_path=file_path,
                direction="incoming",
                limit=max_imports_per_file // 2,  # Fewer incoming to prioritize outgoing
            )
            for neighbor in incoming:
                node_id = neighbor.get("node", {}).get("node_id")
                if node_id and node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    result.import_neighbors.append({
                        "relationship": "imported_by",
                        "source_file": file_path,
                        **neighbor,
                    })
                    result.stats.import_neighbors_retrieved += 1
                    
    async def _retrieve_docs(
        self,
        repo_id: str,
        result: KGCandidateResult,
        seen_node_ids: Set[str],
    ) -> None:
        """Retrieve documentation text nodes (README, docs/, etc.)."""
        
        max_docs = getattr(self._limits, "max_kg_docs_total", 20)
        docs_per_prefix = max(1, max_docs // len(self.DOC_PATH_PREFIXES))

        for prefix in self.DOC_PATH_PREFIXES:
            if result.stats.docs_retrieved >= max_docs:
                break

            remaining = max_docs - result.stats.docs_retrieved
            limit = min(docs_per_prefix, remaining)

            docs = await self._kg.get_text_nodes(
                repo_id=repo_id,
                path_prefix=prefix,
                limit=limit,
            )
            
            for doc in docs:
                node_id = doc.get("node_id")
                if node_id and node_id not in seen_node_ids:
                    seen_node_ids.add(node_id)
                    result.docs.append({
                        "path_prefix": prefix,
                        "node": doc,
                    })
                    result.stats.docs_retrieved += 1
    
    