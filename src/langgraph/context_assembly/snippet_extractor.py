import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.langgraph.context_assembly.base_node import BaseContextAssemblyNode
from src.langgraph.context_assembly.types import WorkflowState
from src.models.schemas.pr_review.pr_patch import PRFilePatch


class SnippetExtractorNode(BaseContextAssemblyNode):
    """Node that extracts code snippets from PR head using cloned repository."""

    def __init__(self):
        super().__init__("snippet_extractor")
        # Initialize file snippet extractor
        from .file_snippet_extractor import FileSnippetExtractor
        self.file_extractor = FileSnippetExtractor(
            max_file_size_mb=5.0,  # Limit file size for performance
            max_line_length=5000,  # Limit line length to avoid memory issues
            encoding_detection_limit=4096
        )

    async def _execute_node_logic(self, state: WorkflowState) -> Dict[str, Any]:
        """Extract code snippets for context items using real file extraction."""
        enriched_candidates = state.get("node_results", {}).get("candidate_enricher", {}).get("enriched_candidates", [])
        patches = state["patches"]
        limits = state["limits"]
        clone_path = state.get("clone_path")

        extracted_items = []
        extraction_stats = {
            "candidates_processed": len(enriched_candidates),
            "snippets_extracted": 0,
            "snippets_truncated": 0,
            "extraction_errors": 0,
            "binary_files_skipped": 0,
            "file_not_found": 0
        }

        # Check if clone_path is available
        if not clone_path:
            self.logger.warning("No clone_path provided - falling back to mock extraction")
            return await self._fallback_mock_extraction(enriched_candidates, patches, limits, extraction_stats)

        self.logger.info(f"Extracting real code snippets from {len(enriched_candidates)} candidates using clone: {clone_path}")

        # Extract snippets using FileSnippetExtractor
        extraction_results = self.file_extractor.extract_multiple_snippets(
            clone_path=clone_path,
            candidates=enriched_candidates
        )

        # Process extraction results
        for i, (candidate, extraction_result) in enumerate(zip(enriched_candidates, extraction_results)):
            try:
                if extraction_result.extraction_success:
                    # Apply preliminary limits to extracted content
                    bounded_snippet = self._apply_snippet_limits(
                        {
                            "content": extraction_result.content,
                            "file_path": extraction_result.file_path,
                            "start_line": extraction_result.start_line,
                            "end_line": extraction_result.end_line,
                            "size": len(extraction_result.content)
                        },
                        limits.max_lines_per_snippet,
                        limits.max_chars_per_item
                    )

                    extracted_item = {
                        **candidate,
                        "code_snippet": bounded_snippet["content"],
                        "original_size": extraction_result.file_size_bytes,
                        "truncated": bounded_snippet["was_truncated"] or extraction_result.is_truncated,
                        "extraction_metadata": {
                            "extracted_at": datetime.utcnow().isoformat(),
                            "source": "clone_repository",
                            "line_count": extraction_result.actual_lines,
                            "encoding": extraction_result.encoding,
                            "actual_start_line": extraction_result.start_line,
                            "actual_end_line": extraction_result.end_line
                        }
                    }

                    extracted_items.append(extracted_item)
                    extraction_stats["snippets_extracted"] += 1

                    if bounded_snippet["was_truncated"] or extraction_result.is_truncated:
                        extraction_stats["snippets_truncated"] += 1

                else:
                    # Handle extraction errors
                    error_msg = extraction_result.extraction_error or "Unknown extraction error"
                    self.logger.debug(f"Failed to extract snippet for {candidate.get('symbol_name', 'unknown')}: {error_msg}")

                    # Categorize errors
                    if "not found" in error_msg.lower():
                        extraction_stats["file_not_found"] += 1
                    elif extraction_result.is_binary:
                        extraction_stats["binary_files_skipped"] += 1
                    else:
                        extraction_stats["extraction_errors"] += 1

            except Exception as e:
                self.logger.warning(f"Error processing extraction result {i}: {e}")
                extraction_stats["extraction_errors"] += 1
                continue

        # Log extraction summary
        success_rate = extraction_stats["snippets_extracted"] / max(extraction_stats["candidates_processed"], 1)
        self.logger.info(
            f"Real code extraction completed: {extraction_stats['snippets_extracted']}/{extraction_stats['candidates_processed']} "
            f"successful ({success_rate:.1%}), {extraction_stats['file_not_found']} files not found, "
            f"{extraction_stats['binary_files_skipped']} binary files skipped"
        )

        # If no items extracted and seed symbols exist, extract seed symbol code as fallback
        seed_set = state.get("seed_set")
        if len(extracted_items) == 0 and seed_set and len(seed_set.seed_symbols) > 0:
            self.logger.warning(
                f"[SNIPPET_EXTRACTOR] No items extracted from {len(enriched_candidates)} candidates. "
                f"Falling back to extract seed symbol code directly."
            )
            extracted_items = await self._extract_seed_symbol_code(seed_set, clone_path, limits)
            extraction_stats["snippets_extracted"] = len(extracted_items)
            extraction_stats["fallback_to_seed_symbols"] = True
            self.logger.info(
                f"[SNIPPET_EXTRACTOR] Extracted {len(extracted_items)} items from seed symbols as fallback"
            )

        return {
            "extracted_items": extracted_items,
            "extraction_stats": extraction_stats,
            "quality_metrics": {
                "extraction_success_rate": success_rate,
                "truncation_rate": (
                    extraction_stats["snippets_truncated"] /
                    max(extraction_stats["snippets_extracted"], 1)
                ),
                "real_code_extraction": True,
                "clone_path_used": clone_path
            }
        }

    async def _fallback_mock_extraction(
        self,
        enriched_candidates: List[Dict],
        patches: List[PRFilePatch],
        limits,
        extraction_stats: Dict
    ) -> Dict[str, Any]:
        """Fallback to mock extraction when clone_path is not available."""
        extracted_items = []

        for candidate in enriched_candidates:
            try:
                # Generate mock code snippet (keep existing logic for backwards compatibility)
                snippet_data = await self._generate_mock_snippet(candidate, patches)

                if snippet_data:
                    # Apply preliminary limits
                    bounded_snippet = self._apply_snippet_limits(
                        snippet_data, limits.max_lines_per_snippet, limits.max_chars_per_item
                    )

                    extracted_item = {
                        **candidate,
                        "code_snippet": bounded_snippet["content"],
                        "original_size": bounded_snippet["original_size"],
                        "truncated": bounded_snippet["was_truncated"],
                        "extraction_metadata": {
                            "extracted_at": datetime.utcnow().isoformat(),
                            "source": "mock_generation",  # Indicate this is mock
                            "line_count": bounded_snippet["line_count"]
                        }
                    }

                    extracted_items.append(extracted_item)
                    extraction_stats["snippets_extracted"] += 1

                    if bounded_snippet["was_truncated"]:
                        extraction_stats["snippets_truncated"] += 1

            except Exception as e:
                self.logger.warning(f"Failed to generate mock snippet for {candidate.get('symbol_name', 'unknown')}: {e}")
                extraction_stats["extraction_errors"] += 1
                continue

        return {
            "extracted_items": extracted_items,
            "extraction_stats": extraction_stats,
            "quality_metrics": {
                "extraction_success_rate": (
                    extraction_stats["snippets_extracted"] /
                    max(extraction_stats["candidates_processed"], 1)
                ),
                "truncation_rate": (
                    extraction_stats["snippets_truncated"] /
                    max(extraction_stats["snippets_extracted"], 1)
                ),
                "real_code_extraction": False,  # Indicate this is mock
                "fallback_reason": "clone_path_unavailable"
            }
        }

    async def _generate_mock_snippet(self, candidate: Dict, patches: List[PRFilePatch]) -> Optional[Dict]:
        """Generate mock code snippet for backwards compatibility."""
        file_path = candidate.get("file_path", "")
        start_line = candidate.get("start_line", 1)
        end_line = candidate.get("end_line", start_line + 10)

        # Generate mock code snippet (existing logic)
        symbol_name = candidate.get("symbol_name", "unknown")
        symbol_type = candidate.get("symbol_type", "function")

        if symbol_type == "function":
            mock_snippet = f"""def {symbol_name}():
    \"\"\"Mock function for context assembly testing.\"\"\"
    # Implementation details would be here
    return None"""
        elif symbol_type == "class":
            mock_snippet = f"""class {symbol_name}:
    \"\"\"Mock class for context assembly testing.\"\"\"

    def __init__(self):
        pass

    def method_example(self):
        return None"""
        else:
            mock_snippet = f"# {symbol_type}: {symbol_name}\n# Mock code snippet"

        return {
            "content": mock_snippet,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "size": len(mock_snippet)
        }

    async def _extract_seed_symbol_code(
        self,
        seed_set,
        clone_path: str,
        limits
    ) -> List[Dict[str, Any]]:
        """
        Extract code snippets directly from seed symbols as fallback.
        
        Args:
            seed_set: SeedSetS0 with seed symbols
            clone_path: Path to cloned repository
            limits: Context pack limits
            
        Returns:
            List of extracted items with code snippets
        """
        extracted_items = []
        
        for seed_symbol in seed_set.seed_symbols:
            try:
                self.logger.info(
                    f"[SNIPPET_EXTRACTOR] Extracting seed symbol code: "
                    f"{seed_symbol.name} from {seed_symbol.file_path} "
                    f"(lines {seed_symbol.start_line}-{seed_symbol.end_line})"
                )
                
                # Extract code snippet for seed symbol
                extraction_result = self.file_extractor.extract_snippet(
                    clone_path=clone_path,
                    file_path=seed_symbol.file_path,
                    start_line=seed_symbol.start_line,
                    end_line=seed_symbol.end_line,
                    max_lines=limits.max_lines_per_snippet
                )
                
                if extraction_result.extraction_success:
                    # Apply limits
                    bounded_snippet = self._apply_snippet_limits(
                        {
                            "content": extraction_result.content,
                            "file_path": extraction_result.file_path,
                            "start_line": extraction_result.start_line,
                            "end_line": extraction_result.end_line,
                            "size": len(extraction_result.content)
                        },
                        limits.max_lines_per_snippet,
                        limits.max_chars_per_item
                    )
                    
                    # Create context item from seed symbol
                    extracted_item = {
                        "item_id": f"seed_{seed_symbol.name}_{seed_symbol.file_path}",
                        "symbol_name": seed_symbol.name,
                        "symbol_type": seed_symbol.kind,
                        "file_path": seed_symbol.file_path,
                        "code_snippet": bounded_snippet["content"],
                        "start_line": seed_symbol.start_line,
                        "end_line": seed_symbol.end_line,
                        "is_seed_symbol": True,
                        "priority": 1,  # Highest priority for seed symbols
                        "relevance_score": 1.0,  # Maximum relevance
                        "source": "seed_symbol_fallback",
                        "original_size": extraction_result.file_size_bytes,
                        "truncated": bounded_snippet["was_truncated"] or extraction_result.is_truncated,
                        "extraction_metadata": {
                            "extracted_at": datetime.utcnow().isoformat(),
                            "source": "seed_symbol_direct_extraction",
                            "line_count": extraction_result.actual_lines,
                            "encoding": extraction_result.encoding,
                            "actual_start_line": extraction_result.start_line,
                            "actual_end_line": extraction_result.end_line
                        }
                    }
                    
                    extracted_items.append(extracted_item)
                    self.logger.info(
                        f"[SNIPPET_EXTRACTOR] Successfully extracted seed symbol code: "
                        f"{seed_symbol.name} ({len(bounded_snippet['content'])} chars)"
                    )
                else:
                    error_msg = extraction_result.extraction_error or "Unknown error"
                    self.logger.warning(
                        f"[SNIPPET_EXTRACTOR] Failed to extract seed symbol code for "
                        f"{seed_symbol.name}: {error_msg}"
                    )
                    
            except Exception as e:
                self.logger.error(
                    f"[SNIPPET_EXTRACTOR] Error extracting seed symbol {seed_symbol.name}: {e}",
                    exc_info=True
                )
                continue
        
        return extracted_items

    def _apply_snippet_limits(self, snippet_data: Dict, max_lines: int, max_chars: int) -> Dict:
        """Apply size limits to extracted snippet."""
        content = snippet_data["content"]
        original_size = len(content)

        # Apply line limit
        lines = content.split('\n')
        if len(lines) > max_lines:
            content = '\n'.join(lines[:max_lines]) + '\n... [truncated] ...'

        # Apply character limit
        if len(content) > max_chars:
            content = content[:max_chars - 20] + '\n... [truncated] ...'

        return {
            "content": content,
            "original_size": original_size,
            "final_size": len(content),
            "was_truncated": len(content) < original_size,
            "line_count": len(content.split('\n'))
        }

