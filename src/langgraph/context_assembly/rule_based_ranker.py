"""
Rule-Based Context Ranker

High-performance, deterministic context ranking without LLM dependencies.
Uses structural relationships, file proximity, and semantic heuristics for relevance scoring.
"""

import logging
import re
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from difflib import SequenceMatcher

from src.models.schemas.pr_review.seed_set import SeedSetS0, SeedSymbol
from src.models.schemas.pr_review.pr_patch import PRFilePatch

logger = logging.getLogger(__name__)


@dataclass
class RelevanceFeatures:
    """Features extracted for rule-based relevance scoring."""

    # Direct relevance indicators
    is_seed_symbol: bool = False
    is_same_file: bool = False
    file_distance: float = 0.0  # 0.0 = same file, 1.0 = unrelated

    # Symbol relationship features
    relationship_strength: float = 0.0  # Based on call frequency, containment
    relationship_type: str = "unknown"  # CALLS, CONTAINS, IMPORTS, etc.
    call_frequency: int = 0

    # Code quality indicators
    has_documentation: bool = False
    is_test_file: bool = False
    is_config_file: bool = False
    is_main_interface: bool = False  # Public API, main classes

    # Naming and semantic similarity
    name_similarity: float = 0.0  # Jaccard similarity with seed symbols
    path_similarity: float = 0.0  # Path component similarity

    # Code characteristics
    lines_of_code: int = 0
    complexity_estimate: float = 0.0
    recent_changes: bool = False


class RuleBasedContextRanker:
    """
    Rule-based context ranking using structural relationships and heuristics.

    Provides deterministic, fast, and cost-free context relevance scoring
    based on code structure, file organization, and semantic patterns.
    """

    def __init__(
        self,
        min_relevance_threshold: float = 0.1,
        file_extension_weights: Optional[Dict[str, float]] = None,
        relationship_weights: Optional[Dict[str, float]] = None
    ):
        """
        Initialize rule-based ranker.

        Args:
            min_relevance_threshold: Minimum score to include in results
            file_extension_weights: Custom weights for file types
            relationship_weights: Custom weights for relationship types
        """
        self.min_relevance_threshold = min_relevance_threshold

        # Default file type priorities
        self.file_extension_weights = file_extension_weights or {
            '.py': 1.0,      # Python source
            '.js': 1.0,      # JavaScript source
            '.ts': 1.0,      # TypeScript source
            '.tsx': 1.0,     # TypeScript React
            '.jsx': 0.9,     # JavaScript React
            '.java': 1.0,    # Java source
            '.cpp': 1.0,     # C++ source
            '.h': 0.8,       # Header files
            '.md': 0.3,      # Documentation
            '.json': 0.4,    # Configuration
            '.yml': 0.4,     # Configuration
            '.yaml': 0.4,    # Configuration
            '.txt': 0.2,     # Text files
        }

        # Relationship type importance
        self.relationship_weights = relationship_weights or {
            'CALLS': 0.8,           # Direct function calls
            'CALLED_BY': 0.8,       # Reverse calls
            'CONTAINS_SYMBOL': 0.6,  # Containment relationship
            'CONTAINED_BY': 0.6,    # Reverse containment
            'IMPORTS': 0.5,         # Import dependencies
            'IMPORTED_BY': 0.5,     # Reverse imports
            'IMPLEMENTS': 0.7,      # Interface implementation
            'EXTENDS': 0.7,         # Class inheritance
            'REFERENCES': 0.4,      # Variable references
            'DEFINES': 0.5,         # Symbol definitions
        }

        # Compile regex patterns for efficiency
        self._test_file_pattern = re.compile(r'(test_|_test\.|tests?/|spec/|__tests__/)', re.IGNORECASE)
        self._config_file_pattern = re.compile(r'\.(json|yml|yaml|toml|ini|cfg|conf)$', re.IGNORECASE)
        self._doc_pattern = re.compile(r'\.(md|rst|txt|doc)$', re.IGNORECASE)

    def score_relevance_batch(
        self,
        candidates: List[Dict],
        seed_set: SeedSetS0,
        patches: List[PRFilePatch]
    ) -> List[Dict]:
        """
        Score relevance for a batch of context candidates.

        Args:
            candidates: List of KG candidate dictionaries
            seed_set: PR seed symbols and files
            patches: PR file patches for additional context

        Returns:
            List of candidates with added relevance_score field
        """
        logger.info(f"Scoring {len(candidates)} candidates using rule-based ranking")

        # Pre-compute seed information for efficiency
        seed_info = self._extract_seed_information(seed_set, patches)

        scored_candidates = []
        for candidate in candidates:
            try:
                # Extract features from candidate
                features = self._extract_features(candidate, seed_info)

                # Calculate relevance score
                relevance_score = self._calculate_relevance_score(features)

                # Add score to candidate (maintaining original structure)
                scored_candidate = candidate.copy()
                scored_candidate['relevance_score'] = relevance_score
                scored_candidate['ranking_features'] = features.__dict__

                # Only include candidates above threshold
                if relevance_score >= self.min_relevance_threshold:
                    scored_candidates.append(scored_candidate)

            except Exception as e:
                logger.warning(f"Failed to score candidate {candidate.get('item_id', 'unknown')}: {e}")
                # Include with minimal score to avoid losing data
                scored_candidate = candidate.copy()
                scored_candidate['relevance_score'] = 0.01
                scored_candidates.append(scored_candidate)

        # Sort by relevance score (highest first)
        scored_candidates.sort(key=lambda x: x['relevance_score'], reverse=True)

        logger.info(
            f"Rule-based ranking complete: {len(scored_candidates)} candidates above threshold "
            f"(avg score: {sum(c['relevance_score'] for c in scored_candidates) / max(len(scored_candidates), 1):.3f})"
        )

        return scored_candidates

    def _extract_seed_information(self, seed_set: SeedSetS0, patches: List[PRFilePatch]) -> Dict:
        """Extract and pre-process seed information for efficient scoring."""
        seed_info = {
            'symbol_names': set(),
            'qualified_names': set(),
            'file_paths': set(),
            'file_extensions': set(),
            'directory_paths': set(),
            'hunk_line_ranges': {},  # file_path -> [(start, end), ...]
            'changed_functions': set(),
        }

        # Process seed symbols
        for symbol in seed_set.seed_symbols:
            seed_info['symbol_names'].add(symbol.name.lower())
            if symbol.qualified_name:
                seed_info['qualified_names'].add(symbol.qualified_name.lower())

            file_path = symbol.file_path
            seed_info['file_paths'].add(file_path)
            seed_info['directory_paths'].add('/'.join(file_path.split('/')[:-1]))

            # Extract file extension
            if '.' in file_path:
                ext = '.' + file_path.split('.')[-1]
                seed_info['file_extensions'].add(ext)

        # Process seed files
        for seed_file in seed_set.seed_files:
            file_path = seed_file.file_path
            seed_info['file_paths'].add(file_path)
            seed_info['directory_paths'].add('/'.join(file_path.split('/')[:-1]))

        # Process patches to extract hunk information
        for patch in patches:
            if patch.file_path not in seed_info['hunk_line_ranges']:
                seed_info['hunk_line_ranges'][patch.file_path] = []

            for hunk in patch.hunks:
                seed_info['hunk_line_ranges'][patch.file_path].append(
                    (hunk.new_start, hunk.new_start + hunk.new_count)
                )

        return seed_info

    def _extract_features(self, candidate: Dict, seed_info: Dict) -> RelevanceFeatures:
        """Extract relevance features from a context candidate."""
        features = RelevanceFeatures()

        # Basic candidate information
        symbol_name = candidate.get('symbol_name', '').lower()
        file_path = candidate.get('file_path', '')
        qualified_name = candidate.get('qualified_name', '').lower()

        # Direct relevance checks
        features.is_seed_symbol = (
            symbol_name in seed_info['symbol_names'] or
            qualified_name in seed_info['qualified_names']
        )

        features.is_same_file = file_path in seed_info['file_paths']

        # File distance calculation
        features.file_distance = self._calculate_file_distance(file_path, seed_info)

        # File type classification
        features.is_test_file = bool(self._test_file_pattern.search(file_path))
        features.is_config_file = bool(self._config_file_pattern.search(file_path))

        # Documentation detection
        features.has_documentation = (
            bool(candidate.get('docstring')) or
            bool(candidate.get('documentation')) or
            bool(self._doc_pattern.search(file_path))
        )

        # Relationship analysis
        relationship_type = candidate.get('relationship_type', 'unknown')
        features.relationship_type = relationship_type
        features.relationship_strength = self.relationship_weights.get(relationship_type, 0.0)
        features.call_frequency = candidate.get('call_frequency', 0)

        # Name similarity
        features.name_similarity = self._calculate_name_similarity(symbol_name, seed_info['symbol_names'])
        features.path_similarity = self._calculate_path_similarity(file_path, seed_info['file_paths'])

        # Code characteristics
        features.lines_of_code = len(candidate.get('code_snippet', '').split('\n'))
        features.complexity_estimate = self._estimate_complexity(candidate.get('code_snippet', ''))

        # Interface detection (public methods, classes, main functions)
        features.is_main_interface = self._is_main_interface(candidate)

        return features

    def _calculate_relevance_score(self, features: RelevanceFeatures) -> float:
        """Calculate final relevance score from extracted features."""
        score = 0.0

        # Direct relevance (highest weight)
        if features.is_seed_symbol:
            score += 0.9  # Nearly maximum relevance for changed symbols

        # File proximity (very important)
        if features.is_same_file:
            score += 0.7
        else:
            # Decay based on file distance
            file_proximity_score = max(0, 0.5 * (1.0 - features.file_distance))
            score += file_proximity_score

        # Relationship-based scoring
        relationship_score = features.relationship_strength
        if features.call_frequency > 0:
            # Boost score for frequently called functions
            frequency_boost = min(0.2, features.call_frequency * 0.05)
            relationship_score += frequency_boost
        score += relationship_score * 0.6

        # Code quality and type bonuses
        if features.has_documentation:
            score += 0.1  # Well-documented code is valuable

        if features.is_test_file:
            score += 0.15  # Tests provide valuable context

        if features.is_main_interface:
            score += 0.1  # Public interfaces are important

        # Name similarity bonus
        if features.name_similarity > 0.3:
            score += features.name_similarity * 0.2

        # Path similarity bonus
        if features.path_similarity > 0.3:
            score += features.path_similarity * 0.15

        # Complexity penalty (prefer simpler, more focused code)
        if features.complexity_estimate > 0.7:
            score -= 0.05

        # File type weighting
        file_ext = self._get_file_extension(features)
        if file_ext in self.file_extension_weights:
            score *= self.file_extension_weights[file_ext]

        # Ensure score is in valid range
        return max(0.0, min(1.0, score))

    def _calculate_file_distance(self, file_path: str, seed_info: Dict) -> float:
        """Calculate normalized distance between file and seed files."""
        if not file_path or not seed_info['file_paths']:
            return 1.0

        min_distance = 1.0
        file_parts = file_path.split('/')

        for seed_file in seed_info['file_paths']:
            seed_parts = seed_file.split('/')

            # Calculate directory overlap
            common_dirs = 0
            for i, (part1, part2) in enumerate(zip(file_parts[:-1], seed_parts[:-1])):
                if part1 == part2:
                    common_dirs += 1
                else:
                    break

            # Distance based on directory structure
            max_depth = max(len(file_parts), len(seed_parts))
            if max_depth > 0:
                distance = 1.0 - (common_dirs / max_depth)
                min_distance = min(min_distance, distance)

        return min_distance

    def _calculate_name_similarity(self, name: str, seed_names: Set[str]) -> float:
        """Calculate maximum name similarity with any seed symbol."""
        if not name or not seed_names:
            return 0.0

        max_similarity = 0.0
        for seed_name in seed_names:
            # Use sequence matcher for fuzzy string matching
            similarity = SequenceMatcher(None, name, seed_name).ratio()
            max_similarity = max(max_similarity, similarity)

        return max_similarity

    def _calculate_path_similarity(self, path: str, seed_paths: Set[str]) -> float:
        """Calculate maximum path similarity with any seed file."""
        if not path or not seed_paths:
            return 0.0

        max_similarity = 0.0
        path_parts = set(path.split('/'))

        for seed_path in seed_paths:
            seed_parts = set(seed_path.split('/'))
            if path_parts and seed_parts:
                # Jaccard similarity of path components
                intersection = len(path_parts & seed_parts)
                union = len(path_parts | seed_parts)
                similarity = intersection / union if union > 0 else 0.0
                max_similarity = max(max_similarity, similarity)

        return max_similarity

    def _estimate_complexity(self, code_snippet: str) -> float:
        """Estimate code complexity based on simple heuristics."""
        if not code_snippet:
            return 0.0

        lines = code_snippet.split('\n')
        complexity_indicators = 0

        for line in lines:
            line = line.strip()
            # Count control flow statements
            if any(keyword in line for keyword in ['if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'except:', 'with ']):
                complexity_indicators += 1
            # Count function definitions
            if any(keyword in line for keyword in ['def ', 'function ', 'class ']):
                complexity_indicators += 1

        # Normalize by number of lines
        return min(1.0, complexity_indicators / max(len(lines), 1))

    def _is_main_interface(self, candidate: Dict) -> bool:
        """Detect if candidate represents a main interface or public API."""
        symbol_name = candidate.get('symbol_name', '')
        symbol_type = candidate.get('symbol_type', '')
        code_snippet = candidate.get('code_snippet', '')

        # Check for main function patterns
        if symbol_name.lower() in ['main', 'init', '__init__', 'setup', 'configure']:
            return True

        # Check for class definitions
        if symbol_type in ['class', 'interface']:
            return True

        # Check for public method indicators
        if not symbol_name.startswith('_') and symbol_type in ['function', 'method']:
            # Look for public API patterns in code
            if any(pattern in code_snippet for pattern in ['export', 'public', '@api', 'def ']):
                return True

        return False

    def _get_file_extension(self, features: RelevanceFeatures) -> str:
        """Extract file extension from features or candidate."""
        # This is a simplified implementation - in real usage you'd get this from the candidate
        return '.py'  # Default assumption for now

    def remove_duplicates(
        self,
        scored_items: List[Dict],
        similarity_threshold: float = 0.85
    ) -> List[Dict]:
        """
        Remove duplicate or highly similar context items.
        
        Args:
            scored_items: List of scored context items
            similarity_threshold: Threshold for considering items duplicates (0.0-1.0)
            
        Returns:
            Deduplicated list of items
        """
        if not scored_items:
            return []
        
        # Simple deduplication based on item_id or file_path + symbol_name
        seen = set()
        deduplicated = []
        
        for item in scored_items:
            # Create unique key from item_id or file_path + symbol_name
            item_id = item.get('item_id')
            if item_id:
                key = item_id
            else:
                file_path = item.get('file_path', '')
                symbol_name = item.get('symbol_name', item.get('name', ''))
                key = f"{file_path}:{symbol_name}"
            
            if key not in seen:
                seen.add(key)
                deduplicated.append(item)
        
        logger.debug(f"Removed {len(scored_items) - len(deduplicated)} duplicate items")
        return deduplicated

    def get_scoring_stats(self, scored_candidates: List[Dict]) -> Dict:
        """Get statistics about the scoring results."""
        if not scored_candidates:
            return {"total": 0, "avg_score": 0.0, "score_distribution": {}}

        scores = [c['relevance_score'] for c in scored_candidates]

        # Score distribution buckets
        distribution = {
            "high (>0.7)": len([s for s in scores if s > 0.7]),
            "medium (0.4-0.7)": len([s for s in scores if 0.4 <= s <= 0.7]),
            "low (0.1-0.4)": len([s for s in scores if 0.1 <= s < 0.4]),
            "very_low (<0.1)": len([s for s in scores if s < 0.1])
        }

        return {
            "total": len(scores),
            "avg_score": sum(scores) / len(scores),
            "max_score": max(scores),
            "min_score": min(scores),
            "score_distribution": distribution
        }