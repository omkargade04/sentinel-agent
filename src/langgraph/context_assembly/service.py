"""
Context Assembly Service

Production-grade thin wrapper service for context assembly.
Delegates to ContextAssemblyGraph for actual processing.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import UUID
from dataclasses import dataclass, field

from src.models.schemas.pr_review.context_pack import (
    ContextPack, ContextItem, ContextPackLimits, ContextPackStats,
    ContextSource, ContextItemType
)
from src.models.schemas.pr_review.seed_set import SeedSetS0
from src.models.schemas.pr_review.pr_patch import PRFilePatch

from .context_graph import ContextAssemblyGraph
from .circuit_breaker import CircuitBreaker
from .exceptions import ContextAssemblyError

logger = logging.getLogger(__name__)


@dataclass
class AssemblyConfig:
    """Configuration for context assembly process."""

    # Circuit breaker settings
    failure_threshold: int = 5
    recovery_timeout: int = 60

    # Timeouts
    operation_timeout_seconds: int = 300

    # Context limits (passed to graph)
    max_context_items: int = 35
    max_total_characters: int = 120_000
    max_lines_per_snippet: int = 120
    max_chars_per_item: int = 2000
    max_hops: int = 1
    max_neighbors_per_seed: int = 8


@dataclass
class AssemblyMetrics:
    """Metrics collected during context assembly."""

    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Processing stats
    kg_candidates_processed: int = 0
    context_items_generated: int = 0
    items_truncated: int = 0

    # Performance
    total_time_ms: float = 0.0

    # Graph metrics
    workflow_execution_time_seconds: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Calculate total processing duration."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "kg_candidates_processed": self.kg_candidates_processed,
            "context_items_generated": self.context_items_generated,
            "items_truncated": self.items_truncated,
            "total_time_ms": self.total_time_ms,
            "workflow_execution_time_seconds": self.workflow_execution_time_seconds,
        }


class ContextAssemblyService:
    """
    Production-grade context assembly service.

    This service is a thin wrapper that:
    - Accepts typed inputs (SeedSetS0, PRFilePatch, etc.)
    - Delegates to ContextAssemblyGraph for actual processing
    - Converts graph output back to typed ContextPack

    The actual assembly logic (enrichment, scoring, ranking, limits)
    is handled by the LangGraph workflow nodes.
    """

    def __init__(
        self,
        config: Optional[AssemblyConfig] = None,
    ):
        """
        Initialize ContextAssemblyService.

        Args:
            config: Assembly configuration
        """
        self.config = config or AssemblyConfig()

        # Build graph config from service config
        graph_config = {
            "failure_threshold": self.config.failure_threshold,
            "recovery_timeout": self.config.recovery_timeout,
            "workflow_timeout": self.config.operation_timeout_seconds,
            "max_context_items": self.config.max_context_items,
            "max_total_characters": self.config.max_total_characters,
            "max_lines_per_snippet": self.config.max_lines_per_snippet,
            "max_chars_per_item": self.config.max_chars_per_item,
            "max_hops": self.config.max_hops,
            "max_neighbors_per_seed": self.config.max_neighbors_per_seed,
        }

        # Initialize the context assembly graph
        self.context_graph = ContextAssemblyGraph(config=graph_config)

        # Circuit breaker for service-level protection
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.failure_threshold,
            recovery_timeout=self.config.recovery_timeout,
            name="context_assembly_service"
        )

        # Service-level metrics
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0

        logger.info(
            f"Initialized ContextAssemblyService: "
            f"max_items={self.config.max_context_items}, "
            f"max_chars={self.config.max_total_characters}"
        )

    async def assemble_context(
        self,
        repo_id: UUID,
        github_repo_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str,
        seed_set: SeedSetS0,
        patches: List[PRFilePatch],
        kg_candidates: Dict[str, Any],
        limits: ContextPackLimits,
        clone_path: Optional[str] = None,
        kg_commit_sha: Optional[str] = None
    ) -> ContextPack:
        """
        Assemble intelligent context pack by delegating to the graph.

        Args:
            repo_id: Repository UUID
            github_repo_name: Repository name in owner/repo format
            pr_number: Pull request number
            head_sha: PR head commit SHA
            base_sha: PR base commit SHA
            seed_set: Seed symbols and files from PR analysis
            patches: PR file patches
            kg_candidates: Knowledge graph candidates from previous phase
            limits: Hard limits to enforce
            clone_path: Path to cloned repository for code extraction
            kg_commit_sha: Optional KG commit SHA

        Returns:
            ContextPack with bounded context items

        Raises:
            ContextAssemblyError: If assembly fails
        """
        metrics = AssemblyMetrics()
        self._total_requests += 1

        try:
            candidates_list = kg_candidates.get('candidates', [])
            metrics.kg_candidates_processed = len(candidates_list)

            logger.info(
                f"Starting context assembly for {github_repo_name}#{pr_number} "
                f"with {metrics.kg_candidates_processed} KG candidates"
            )

            # Serialize inputs for graph
            seed_symbols_dict = self._serialize_seed_set(seed_set)
            patches_dict = self._serialize_patches(patches)

            # Delegate to graph
            result = await self.context_graph.assemble_context(
                seed_symbols=seed_symbols_dict,
                kg_candidates=candidates_list,
                pr_patches=patches_dict,
                clone_path=clone_path
            )

            # Extract stats from result
            stats = result.get("stats", {})
            metrics.context_items_generated = stats.get("selected_items", 0)
            metrics.items_truncated = stats.get("items_truncated", 0)
            metrics.workflow_execution_time_seconds = stats.get("execution_time_seconds", 0)

            # Convert graph output to ContextPack
            context_pack = self._build_context_pack(
                result=result,
                repo_id=repo_id,
                github_repo_name=github_repo_name,
                pr_number=pr_number,
                head_sha=head_sha,
                base_sha=base_sha,
                kg_commit_sha=kg_commit_sha,
                seed_set=seed_set,
                patches=patches,
                limits=limits,
                metrics=metrics
            )

            metrics.end_time = datetime.utcnow()
            metrics.total_time_ms = metrics.duration_seconds * 1000

            self._successful_requests += 1

            logger.info(
                f"Context assembly complete for {github_repo_name}#{pr_number}: "
                f"{len(context_pack.context_items)} items, "
                f"{context_pack.total_context_characters} chars, "
                f"{metrics.total_time_ms:.0f}ms"
            )

            return context_pack

        except ContextAssemblyError:
            self._failed_requests += 1
            raise

        except Exception as e:
            self._failed_requests += 1
            metrics.end_time = datetime.utcnow()
            logger.error(
                f"Context assembly failed for {github_repo_name}#{pr_number}: {e}. "
                f"Duration: {metrics.duration_seconds:.1f}s"
            )
            raise ContextAssemblyError(f"Assembly failed: {str(e)}") from e

    def _serialize_seed_set(self, seed_set: SeedSetS0) -> List[Dict[str, Any]]:
        """Serialize SeedSetS0 to list of dicts for graph."""
        return [
            {
                "name": symbol.name,
                "type": symbol.type,
                "file_path": symbol.file_path,
                "line_number": symbol.line_number,
            }
            for symbol in seed_set.seed_symbols
        ]

    def _serialize_patches(self, patches: List[PRFilePatch]) -> List[Dict[str, Any]]:
        """Serialize PRFilePatch list to dicts for graph."""
        return [
            {
                "file_path": patch.file_path,
                "additions": patch.additions,
                "deletions": patch.deletions,
                "changes": patch.changes,
                "patch": patch.patch if hasattr(patch, 'patch') else "",
                "status": patch.status,
            }
            for patch in patches
        ]

    def _build_context_pack(
        self,
        result: Dict[str, Any],
        repo_id: UUID,
        github_repo_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str,
        kg_commit_sha: Optional[str],
        seed_set: SeedSetS0,
        patches: List[PRFilePatch],
        limits: ContextPackLimits,
        metrics: AssemblyMetrics
    ) -> ContextPack:
        """Build ContextPack from graph result."""
        context_items_data = result.get("context_items", [])
        stats_data = result.get("stats", {})

        # Convert dict items to ContextItem objects
        context_items = []
        for i, item_data in enumerate(context_items_data):
            try:
                item = ContextItem(
                    item_id=item_data.get('item_id', f"ctx_{i}"),
                    source=self._determine_source(item_data),
                    item_type=self._determine_item_type(item_data),
                    file_path=item_data.get('file_path', ''),
                    start_line=item_data.get('start_line'),
                    end_line=item_data.get('end_line'),
                    title=self._generate_item_title(item_data),
                    snippet=item_data.get('code_snippet', ''),
                    relevance_score=item_data.get('relevance_score', 0.0),
                    priority=item_data.get('priority', 5),
                    truncated=item_data.get('truncated', False),
                    original_size=item_data.get('original_size'),
                    provenance=item_data.get('provenance', {})
                )
                context_items.append(item)
            except Exception as e:
                logger.warning(f"Failed to create ContextItem from data: {e}")
                continue

        # Build stats
        stats = ContextPackStats(
            total_items=len(context_items),
            total_characters=sum(item.character_count for item in context_items),
            items_by_type={
                item_type: len([item for item in context_items if item.item_type == item_type])
                for item_type in set(item.item_type for item in context_items)
            } if context_items else {},
            items_by_source={
                source: len([item for item in context_items if item.source == source])
                for source in set(item.source for item in context_items)
            } if context_items else {},
            items_truncated=stats_data.get("items_truncated", 0),
            kg_symbols_found=len([item for item in context_items if item.source == ContextSource.CANONICAL]),
            kg_symbols_missing=len(seed_set.seed_symbols) - len([
                item for item in context_items
                if item.item_type == ContextItemType.CHANGED_SYMBOL
            ])
        )

        context_pack = ContextPack(
            repo_id=repo_id,
            github_repo_name=github_repo_name,
            pr_number=pr_number,
            head_sha=head_sha,
            base_sha=base_sha,
            kg_commit_sha=kg_commit_sha,
            patches=patches,
            seed_set=seed_set,
            context_items=context_items,
            limits=limits,
            stats=stats,
            assembly_timestamp=datetime.utcnow().isoformat(),
            assembly_duration_ms=int(metrics.duration_seconds * 1000)
        )

        # Validate limits
        if context_pack.total_context_characters > limits.max_total_characters:
            logger.warning(
                f"Context pack exceeds character limit: "
                f"{context_pack.total_context_characters} > {limits.max_total_characters}"
            )

        return context_pack

    def _determine_source(self, item_data: Dict[str, Any]) -> ContextSource:
        """Determine context source from item data."""
        source = item_data.get('source', 'unknown')
        if source == 'kg' or source == 'canonical':
            return ContextSource.CANONICAL
        elif source == 'fallback':
            return ContextSource.OVERLAY
        else:
            return ContextSource.OVERLAY

    def _determine_item_type(self, item_data: Dict[str, Any]) -> ContextItemType:
        """Determine context item type from item data."""
        if item_data.get('is_seed_symbol'):
            return ContextItemType.CHANGED_SYMBOL
        elif item_data.get('symbol_type') == 'test':
            return ContextItemType.TEST_FILE
        elif item_data.get('relationship_type') in ['calls', 'called_by', 'uses', 'used_by']:
            return ContextItemType.NEIGHBOR_SYMBOL
        elif item_data.get('file_path', '').endswith(('.md', '.txt', '.rst')):
            return ContextItemType.DOC_CONTEXT
        elif item_data.get('relationship_type') == 'imports':
            return ContextItemType.IMPORT_FILE
        else:
            return ContextItemType.FILE_CONTEXT

    def _generate_item_title(self, item_data: Dict[str, Any]) -> str:
        """Generate human-readable title for context item."""
        symbol_name = item_data.get('symbol_name', 'unknown')
        symbol_type = item_data.get('symbol_type', 'symbol')
        file_path = item_data.get('file_path', '')

        if item_data.get('is_seed_symbol'):
            return f"{symbol_type.title()}: {symbol_name} (modified)"
        else:
            return f"{symbol_type.title()}: {symbol_name} in {file_path}"

    def get_metrics(self) -> Dict[str, Any]:
        """Get current service metrics for monitoring."""
        success_rate = (
            self._successful_requests / self._total_requests
            if self._total_requests > 0 else 1.0
        )

        return {
            "service_metrics": {
                "total_requests": self._total_requests,
                "successful_requests": self._successful_requests,
                "failed_requests": self._failed_requests,
                "success_rate": success_rate,
            },
            "circuit_breaker": {
                "state": self.circuit_breaker.state,
                "failure_count": self.circuit_breaker.failure_count,
            },
            "config": {
                "max_context_items": self.config.max_context_items,
                "max_total_characters": self.config.max_total_characters,
                "failure_threshold": self.config.failure_threshold
            },
            "graph_metrics": self.context_graph.get_metrics()
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on context assembly service."""
        service_health = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "service": "context_assembly",
            "components": {}
        }

        # Check graph health
        graph_health = await self.context_graph.health_check()
        service_health["components"]["context_graph"] = graph_health

        # Propagate status
        if graph_health.get("status") != "healthy":
            service_health["status"] = graph_health.get("status", "degraded")

        # Check service-level success rate
        if self._total_requests > 10:
            success_rate = self._successful_requests / self._total_requests
            service_health["components"]["success_rate"] = {
                "status": "healthy" if success_rate >= 0.90 else "degraded",
                "value": success_rate,
                "threshold": 0.90
            }

            if success_rate < 0.50:
                service_health["status"] = "unhealthy"
            elif success_rate < 0.90:
                service_health["status"] = "degraded"

        return service_health
