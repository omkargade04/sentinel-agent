"""
Diff Processor Node Implementation

Node 2 in the Review Generation workflow.
Builds mapping structures for deterministic diff anchoring using PRHunk infrastructure.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from src.services.pr_review.review_generation.base_node import BaseReviewGenerationNode
from src.services.pr_review.review_generation.circuit_breaker import CircuitBreaker
from src.services.pr_review.review_generation.schema import (
    DiffMappings,
    FileDiffMapping,
    HunkMapping,
)

logger = logging.getLogger(__name__)

class DiffProcessorNode(BaseReviewGenerationNode):
    """
    Node 2: Build mapping structures for diff anchoring.
    
    This node processes PRFilePatch[] and builds:
    - file_path → hunk_id → line mappings
    - Allowed anchors list (valid file_path, hunk_id pairs)
    - Reverse lookup: new_line → (hunk_id, line_in_hunk)
    - Changed line indexes for each hunk
    
    Output is used by:
    - PromptBuilder: to constrain LLM to valid anchors
    - FindingAnchorer: to map evidence citations to precise diff positions
    """
    
    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(
            name="diff_processor",
            timeout_seconds=15.0,
            circuit_breaker=circuit_breaker,
            max_retries=2
        )
        
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the diff processor node."""
        return await self._execute_node_logic(state)
    
    async def _execute_node_logic(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process patches and build diff mapping structures.
        
        Args:
            state: Workflow state containing context_pack with patches
            
        Returns:
            Dict with diff_mappings key containing DiffMappings
        """
        self.logger.info("Processing diff patches for anchoring structures")
        
        context_pack = state["context_pack"]
        patches = context_pack["patches"]
        
        if not patches:
            self.logger.warning("No patches found in context pack")
            return {"diff_mappings": self._create_empty_diff_mappings().model_dump()}
        
        # Build mappings from patches
        file_mappings: Dict[str, FileDiffMapping] = {}
        all_file_paths: List[str] = []
        all_hunk_ids: List[str] = []
        allowed_anchors: List[Tuple[str, str]] = []
        line_to_hunk_lookup: Dict[str, Dict[int, Tuple[str, int]]] = {}
        
        total_changed_files = 0
        
        for patch in patches:
            file_path = patch.get("file_path", "")
            if not file_path:
                continue
            
            hunks = patch.get("hunks", [])
            if not hunks:
                # File has no hunks (binary file, deleted file, etc.)
                continue
            
            file_mappings, file_line_lookup, file_changed_lines = self._process_file_patch(
                file_path, hunks
            )
            
            if file_mappings:
                file_mappings[file_path] = file_mappings
                all_file_paths.append(file_path)
                
                # Collect hunk IDs and allowed anchors
                for hunk in file_mappings.hunks:
                    all_hunk_ids.append(hunk.hunk_id)
                    allowed_anchors.append((file_path, hunk.hunk_id))

                # Merge line lookups
                if file_line_lookup:
                    line_to_hunk_lookup[file_path] = file_line_lookup

                total_changed_lines += file_changed_lines
                
        # Build final DiffMappings
        diff_mappings = DiffMappings(
            file_mappings=file_mappings,
            all_file_paths=all_file_paths,
            all_hunk_ids=all_hunk_ids,
            allowed_anchors=allowed_anchors,
            line_to_hunk_lookup=line_to_hunk_lookup,
            total_files=len(file_mappings),
            total_hunks=len(all_hunk_ids),
            total_changed_lines=total_changed_lines
        )
        
        self.logger.info(
            f"Diff processing complete: {diff_mappings.total_files} files, "
            f"{diff_mappings.total_hunks} hunks, "
            f"{diff_mappings.total_changed_lines} changed lines, "
            f"{len(allowed_anchors)} allowed anchors"
        )
        
        return {"diff_mappings": diff_mappings.model_dump()}
    
    def _get_required_state_keys(self) -> List[str]:
        return ["context_pack"]

    def _get_state_type_requirements(self) -> Dict[str, type]:
        return {"context_pack": dict}
    
    def _process_file_patch(
        self,
        file_path: str,
        hunks: List[Dict[str, Any]]
    ) -> Tuple[Optional[FileDiffMapping], Dict[int, Tuple[str, int]], int]:
        """
        Process a single file's patch data.
        
        Args:
            file_path: The file path
            hunks: List of PRHunk dicts from the patch
            
        Returns:
            Tuple of (FileDiffMapping, line_lookup dict, total_changed_lines)
        """
        hunk_mappings: List[HunkMapping] = []
        hunk_ids: List[str] = []
        line_lookup: Dict[int, Tuple[str, int]] = {}
        total_additions = 0
        total_deletions = 0
        total_changed_lines = 0
        
        for hunk in hunks:
            hunk_mapping, hunk_line_lookup = self._process_hunk(hunk)
            
            if hunk_mapping:
                hunk_mappings.append(hunk_mapping)
                hunk_ids.append(hunk_mapping.hunk_id)
                
                # Merge line lookups
                line_lookup.update(hunk_line_lookup)

                # Accumulate stats
                total_additions += len(hunk_mapping.added_line_indexes)
                total_deletions += len(hunk_mapping.removed_line_indexes)
                total_changed_lines += len(hunk_mapping.added_line_indexes)
                
        if not hunk_mappings:
            return None, {}, 0
        
        file_mappings = FileDiffMapping(
            file_path=file_path,
            hunks=hunk_mappings,
            hunk_ids=hunk_ids,
            total_additions=total_additions,
            total_deletions=total_deletions
        )
        
        return file_mappings, line_lookup, total_changed_lines
    
    def _process_hunk(
        self,
        file_path: str,
        hunk_data: Dict[str, Any]
    ) -> Tuple[Optional[HunkMapping], Dict[int, Tuple[str, int]]]:
        """
        Process a single hunk and build its mapping.
        
        Args:
            file_path: The file path this hunk belongs to
            hunk_data: PRHunk dict data
            
        Returns:
            Tuple of (HunkMapping, line_lookup dict for this hunk)
        """
        hunk_id = hunk_data.get("hunk_id", "")
        if not hunk_id:
            self.logger.warning(f"Hunk missing hunk_id in {file_path}")
            return None, {}

        lines = hunk_data.get("lines", [])
        new_start = hunk_data.get("new_start", 1)
        new_count = hunk_data.get("new_count", 0)
        old_start = hunk_data.get("old_start", 1)
        old_count = hunk_data.get("old_count", 0)

        # Build line indexes and reverse lookup
        added_line_indexes: List[int] = []
        removed_line_indexes: List[int] = []
        line_lookup: Dict[int, Tuple[str, int]] = {}

        # Track current line number in new file
        current_new_line = new_start
        
        for line_index, line in enumerate(lines):
            if not line:
                # Empty line - treat as context
                line_lookup[current_new_line] = (hunk_id, line_index)
                current_new_line += 1
                continue

            prefix = line[0] if line else " "

            if prefix == "+":
                # Added line
                added_line_indexes.append(line_index)
                line_lookup[current_new_line] = (hunk_id, line_index)
                current_new_line += 1

            elif prefix == "-":
                # Removed line - doesn't exist in new file
                removed_line_indexes.append(line_index)

            else:
                # Context line (space prefix or other)
                line_lookup[current_new_line] = (hunk_id, line_index)
                current_new_line += 1
                
        hunk_mapping = HunkMapping(
            hunk_id=hunk_id,
            file_path=file_path,
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            lines=lines,
            line_count=len(lines),
            added_line_indexes=added_line_indexes,
            removed_line_indexes=removed_line_indexes
        )

        return hunk_mapping, line_lookup
    
    def _create_empty_diff_mappings(self) -> DiffMappings:
        """Create an empty DiffMappings for edge cases."""
        return DiffMappings(
            file_mappings={},
            all_file_paths=[],
            all_hunk_ids=[],
            allowed_anchors=[],
            line_to_hunk_lookup={},
            total_files=0,
            total_hunks=0,
            total_changed_lines=0
        )
        
    async def _attempt_graceful_degradation(
        self,
        state: Dict[str, Any],
        error: Exception,
        metrics: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Provide fallback when diff processing fails.
        
        Returns minimal diff mappings with available file paths.
        """
        self.logger.warning(f"Using graceful degradation for diff processing: {error}")

        try:
            context_pack = state.get("context_pack", {})
            patches = context_pack.get("patches", [])

            # Extract just file paths for minimal mapping
            file_paths = [
                p.get("file_path", "") 
                for p in patches 
                if p.get("file_path")
            ]

            # Create minimal mappings without hunk details
            fallback_mappings = DiffMappings(
                file_mappings={},
                all_file_paths=file_paths,
                all_hunk_ids=[],
                allowed_anchors=[],
                line_to_hunk_lookup={},
                total_files=len(file_paths),
                total_hunks=0,
                total_changed_lines=0
            )

            self.logger.info(
                f"Graceful degradation: created minimal mappings with {len(file_paths)} files"
            )

            return {"diff_mappings": fallback_mappings.model_dump()}

        except Exception as fallback_error:
            self.logger.error(f"Graceful degradation also failed: {fallback_error}")
            return None