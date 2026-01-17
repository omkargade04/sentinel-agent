"""
Context Assembly Service

Production-grade service for intelligent context assembly using rule-based ranking.
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
from src.core.pr_review_config import ContextAssemblyConfig

from .rule_based_ranker import RuleBasedContextRanker
from .hard_limits_enforcer import HardLimitsEnforcer
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

    # Quality thresholds
    min_relevance_score: float = 0.3
    max_duplicate_similarity: float = 0.85


@dataclass
class AssemblyMetrics:
    """Metrics collected during context assembly."""

    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None

    # Processing stats
    kg_candidates_processed: int = 0
    context_items_generated: int = 0
    items_filtered_by_relevance: int = 0
    items_filtered_by_duplication: int = 0
    items_truncated: int = 0

    # Performance
    scoring_time_ms: float = 0.0
    dedup_time_ms: float = 0.0
    total_time_ms: float = 0.0

    @property
    def duration_seconds(self) -> float:
        """Calculate total processing duration."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()


class ContextAssemblyService:
    """
    Production-grade context assembly service using rule-based ranking.

    Orchestrates the context assembly pipeline with:
    - Rule-based relevance scoring (fast, free, deterministic)
    - Deduplication and similarity filtering
    - Hard limits enforcement
    - Circuit breaker protection for Neo4j
    - Comprehensive error handling
    """

    def __init__(
        self,
        config: Optional[AssemblyConfig] = None,
        context_assembly_config: Optional[ContextAssemblyConfig] = None
    ):
        """
        Initialize ContextAssemblyService.

        Args:
            config: Assembly configuration
            context_assembly_config: Context assembly configuration
        """
        self.config = config or AssemblyConfig()
        self.context_config = context_assembly_config or ContextAssemblyConfig()

        # Initialize rule-based ranker
        self.context_ranker = RuleBasedContextRanker(
            min_relevance_threshold=self.context_config.rule_based_min_threshold
        )

        # Initialize hard limits enforcer
        self.limits_enforcer = HardLimitsEnforcer()

        # Circuit breaker for Neo4j protection
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.failure_threshold,
            recovery_timeout=self.config.recovery_timeout,
            name="context_assembly"
        )

        logger.info(
            f"Initialized ContextAssemblyService: "
            f"min_relevance={self.config.min_relevance_score}, "
            f"max_similarity={self.config.max_duplicate_similarity}"
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
        kg_commit_sha: Optional[str] = None
    ) -> ContextPack:
        """
        Assemble intelligent context pack using rule-based ranking.

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
            kg_commit_sha: Optional KG commit SHA

        Returns:
            ContextPack with bounded context items

        Raises:
            ContextAssemblyError: If assembly fails
        """
        metrics = AssemblyMetrics()

        try:
            logger.info(
                f"Starting context assembly for {github_repo_name}#{pr_number} "
                f"with {len(kg_candidates.get('candidates', []))} KG candidates"
            )

            # Step 1: Extract and enrich candidates
            enriched_candidates = self._enrich_kg_candidates(
                kg_candidates, seed_set, patches, metrics
            )

            # Step 2: Score relevance (rule-based)
            scoring_start = datetime.utcnow()
            scored_candidates = self.context_ranker.score_relevance_batch(
                candidates=enriched_candidates,
                seed_set=seed_set,
                patches=patches
            )
            metrics.scoring_time_ms = (datetime.utcnow() - scoring_start).total_seconds() * 1000

            # Step 3: Filter by minimum relevance
            filtered_candidates = [
                c for c in scored_candidates
                if c.get('relevance_score', 0.0) >= self.config.min_relevance_score
            ]
            metrics.items_filtered_by_relevance = len(scored_candidates) - len(filtered_candidates)

            # Step 4: Rank and deduplicate
            dedup_start = datetime.utcnow()
            ranked_candidates = sorted(
                filtered_candidates,
                key=lambda c: (
                    c.get('relevance_score', 0.0),
                    c.get('is_seed_symbol', False),
                    c.get('affected_by_patch', False),
                ),
                reverse=True
            )

            deduplicated = self.context_ranker.remove_duplicates(
                ranked_candidates, 
                similarity_threshold=self.config.max_duplicate_similarity
            )
            metrics.dedup_time_ms = (datetime.utcnow() - dedup_start).total_seconds() * 1000
            metrics.items_filtered_by_duplication = len(ranked_candidates) - len(deduplicated)

            # Step 5: Apply hard limits and create context items
            context_items = self._apply_limits_and_create_items(
                deduplicated, limits, metrics
            )

            # Step 6: Build final context pack
            context_pack = self._build_context_pack(
                repo_id=repo_id,
                github_repo_name=github_repo_name,
                pr_number=pr_number,
                head_sha=head_sha,
                base_sha=base_sha,
                kg_commit_sha=kg_commit_sha,
                seed_set=seed_set,
                patches=patches,
                context_items=context_items,
                limits=limits,
                metrics=metrics
            )

            metrics.end_time = datetime.utcnow()
            metrics.total_time_ms = metrics.duration_seconds * 1000

            logger.info(
                f"Context assembly complete for {github_repo_name}#{pr_number}: "
                f"{len(context_items)} items, {context_pack.total_context_characters} chars, "
                f"{metrics.total_time_ms:.0f}ms"
            )

            return context_pack

        except Exception as e:
            metrics.end_time = datetime.utcnow()
            logger.error(
                f"Context assembly failed for {github_repo_name}#{pr_number}: {e}. "
                f"Duration: {metrics.duration_seconds:.1f}s"
            )
            raise ContextAssemblyError(f"Assembly failed: {str(e)}") from e

    def _enrich_kg_candidates(
        self,
        kg_candidates: Dict[str, Any],
        seed_set: SeedSetS0,
        patches: List[PRFilePatch],
        metrics: AssemblyMetrics
    ) -> List[Dict[str, Any]]:
        """Enrich KG candidates with additional context metadata."""
        candidates = kg_candidates.get('candidates', [])
        metrics.kg_candidates_processed = len(candidates)

        enriched = []
        seed_names = {seed.name for seed in seed_set.seed_symbols}
        patch_files = {patch.file_path for patch in patches}

        for candidate in candidates:
            enriched_candidate = {
                **candidate,
                'is_seed_symbol': candidate.get('symbol_name', '') in seed_names,
                'affected_by_patch': candidate.get('file_path', '') in patch_files,
            }
            enriched.append(enriched_candidate)

        return enriched

    def _apply_limits_and_create_items(
        self,
        candidates: List[Dict[str, Any]],
        limits: ContextPackLimits,
        metrics: AssemblyMetrics
    ) -> List[ContextItem]:
        """Apply hard limits and create context items."""
        bounded_candidates = self.limits_enforcer.apply_limits(
            candidates=candidates,
            limits=limits
        )

        metrics.items_truncated = self.limits_enforcer.get_truncation_count()

        context_items = []

        for i, candidate in enumerate(bounded_candidates):
            try:
                item = ContextItem(
                    item_id=f"ctx_{candidate.get('symbol_name', 'unknown')}_{i}",
                    source=ContextSource.CANONICAL if candidate.get('source') == 'kg' else ContextSource.OVERLAY,
                    item_type=self._determine_item_type(candidate),
                    file_path=candidate.get('file_path', ''),
                    start_line=candidate.get('start_line'),
                    end_line=candidate.get('end_line'),
                    title=self._generate_item_title(candidate),
                    snippet=candidate.get('code_snippet', ''),
                    relevance_score=candidate.get('relevance_score', 0.0),
                    priority=self._calculate_priority(candidate),
                    truncated=candidate.get('truncated', False),
                    original_size=candidate.get('original_size'),
                    provenance=candidate.get('provenance', {})
                )
                context_items.append(item)

            except Exception as e:
                logger.warning(f"Failed to create context item from candidate {i}: {e}")
                continue

        metrics.context_items_generated = len(context_items)
        return context_items

    def _determine_item_type(self, candidate: Dict[str, Any]) -> ContextItemType:
        """Determine context item type from candidate metadata."""
        if candidate.get('is_seed_symbol'):
            return ContextItemType.CHANGED_SYMBOL
        elif candidate.get('symbol_type') == 'test':
            return ContextItemType.TEST_FILE
        elif candidate.get('relationship_type') in ['calls', 'called_by', 'uses', 'used_by']:
            return ContextItemType.NEIGHBOR_SYMBOL
        elif candidate.get('file_path', '').endswith(('.md', '.txt', '.rst')):
            return ContextItemType.DOC_CONTEXT
        elif candidate.get('relationship_type') == 'imports':
            return ContextItemType.IMPORT_FILE
        else:
            return ContextItemType.FILE_CONTEXT

    def _generate_item_title(self, candidate: Dict[str, Any]) -> str:
        """Generate human-readable title for context item."""
        symbol_name = candidate.get('symbol_name', 'unknown')
        symbol_type = candidate.get('symbol_type', 'symbol')
        file_path = candidate.get('file_path', '')

        if candidate.get('is_seed_symbol'):
            return f"{symbol_type.title()}: {symbol_name} (modified)"
        else:
            return f"{symbol_type.title()}: {symbol_name} in {file_path}"

    def _calculate_priority(self, candidate: Dict[str, Any]) -> int:
        """Calculate priority bucket for candidate."""
        if candidate.get('is_seed_symbol'):
            return 1
        elif candidate.get('affected_by_patch'):
            return 1
        elif candidate.get('relevance_score', 0.0) >= 0.8:
            return 2
        elif candidate.get('relevance_score', 0.0) >= 0.6:
            return 3
        else:
            return 4

    def _build_context_pack(
        self,
        repo_id: UUID,
        github_repo_name: str,
        pr_number: int,
        head_sha: str,
        base_sha: str,
        kg_commit_sha: Optional[str],
        seed_set: SeedSetS0,
        patches: List[PRFilePatch],
        context_items: List[ContextItem],
        limits: ContextPackLimits,
        metrics: AssemblyMetrics
    ) -> ContextPack:
        """Build final context pack with all metadata."""
        stats = ContextPackStats(
            total_items=len(context_items),
            total_characters=sum(item.character_count for item in context_items),
            items_by_type={
                item_type: len([item for item in context_items if item.item_type == item_type])
                for item_type in set(item.item_type for item in context_items)
            },
            items_by_source={
                source: len([item for item in context_items if item.source == source])
                for source in set(item.source for item in context_items)
            },
            items_truncated=metrics.items_truncated,
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

        if context_pack.total_context_characters > limits.max_total_characters:
            raise ContextAssemblyError(
                f"Context pack exceeds character limit: "
                f"{context_pack.total_context_characters} > {limits.max_total_characters}"
            )

        return context_pack

    def get_metrics(self) -> Dict[str, Any]:
        """Get current service metrics for monitoring."""
        return {
            "circuit_breaker": {
                "state": self.circuit_breaker.state,
                "failure_count": self.circuit_breaker.failure_count,
            },
            "config": {
                "min_relevance_score": self.config.min_relevance_score,
                "max_duplicate_similarity": self.config.max_duplicate_similarity,
                "failure_threshold": self.config.failure_threshold
            }
        }
