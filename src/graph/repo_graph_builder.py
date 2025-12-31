"""Building KG for an entire repository.

This module constructs a complete knowledge graph from a repository by:
  1. Walking the directory tree and creating FileNode entries for directories and files.
  2. Delegating per-file processing to FileGraphBuilder for symbol/text extraction.
  3. Building HAS_FILE edges to represent the directory structure.
  4. Aggregating all nodes and edges into a unified graph.

The resulting graph contains:
  * FileNode hierarchy representing the directory structure
  * SymbolNode entries for code files (extracted via Tree-sitter)
  * TextNode entries for documentation files
  * All relationship edges (HAS_FILE, HAS_SYMBOL, HAS_TEXT, CONTAINS_SYMBOL, NEXT_CHUNK)

Large files (>1MB by default) are processed using chunked extraction to prevent
memory issues. Extremely large files (>10MB) are skipped entirely as they are
typically generated code, minified bundles, or data files.
"""

import gc
import logging
from pathlib import Path
from typing import Sequence

from src.parser.extractor.chunked_extractor import ChunkedSymbolExtractor
from src.graph.constants import DEFAULT_EXCLUDED_DIRS, DEFAULT_EXCLUDED_FILES
from src.graph.file_graph_builder import FileGraphBuilder
from src.graph.graph_types import FileNode, KnowledgeGraphEdge, KnowledgeGraphEdgeType, KnowledgeGraphNode, SymbolNode, TextNode
from src.models.graph.indexing_stats import IndexingStats
from src.models.graph.repo_graph_result import RepoGraphResult

logger = logging.getLogger(__name__)

class RepoGraphBuilder:
    """Builds a complete knowledge graph from a repository.
    
    This class orchestrates the construction of a knowledge graph by:
      1. Walking the repository directory tree.
      2. Creating FileNode entries for all directories and files.
      3. Delegating per-file parsing to FileGraphBuilder.
      4. Building the directory structure via HAS_FILE edges.
      5. Aggregating all nodes and edges into a single graph.
    
    The builder supports excluding certain directories and files from indexing,
    and tracks statistics about the indexing process.
    
    Example:
        builder = RepoGraphBuilder(
            repo_id="my-repo-123",
            commit_sha="abc123def456",
            repo_root=Path("/path/to/repo"),
        )
        result = builder.build()
        # result.nodes, result.edges contain the full graph
    """
    def __init__(
        self,
        repo_id: str,
        commit_sha: str,
        repo_root: Path | str,
        excluded_dirs: frozenset[str] | None = None,
        excluded_files: frozenset[str] | None = None,
        max_file_size_bytes: int = 1_000_000,  # 1MB default - files above this use chunked processing
        max_absolute_file_size_bytes: int = 10_000_000,  # 10MB - files above this are always skipped
        max_symbols_per_file: int = 500,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        symbol_batch_size: int = 50,  # Batch size for chunked extraction
    ):
        """Initialize the RepoGraphBuilder.
        
        Args:
            repo_id: Unique identifier for the repository.
            commit_sha: The commit SHA being indexed (used for symbol versioning).
            repo_root: Path to the root directory of the repository.
            excluded_dirs: Set of directory names to exclude. Defaults to common
                build/cache directories.
            excluded_files: Set of file names to exclude. Defaults to lock files
                and config files.
            max_file_size_bytes: Threshold for normal processing (in bytes). Files
                above this size but below max_absolute_file_size_bytes are processed
                using memory-bounded chunked extraction.
            max_absolute_file_size_bytes: Hard limit for file size (in bytes). Files
                above this are always skipped (typically generated/minified code).
            max_symbols_per_file: Maximum symbols to extract per file.
            chunk_size: Character chunk size for text files.
            chunk_overlap: Overlap between text chunks.
            symbol_batch_size: Number of symbols per batch when using chunked extraction.
        """
        self.repo_id = repo_id
        self.commit_sha = commit_sha
        self.repo_root = Path(repo_root) if isinstance(repo_root, str) else repo_root
        self.excluded_dirs = excluded_dirs or DEFAULT_EXCLUDED_DIRS
        self.excluded_files = excluded_files or DEFAULT_EXCLUDED_FILES
        self.max_file_size_bytes = max_file_size_bytes
        self.max_absolute_file_size_bytes = max_absolute_file_size_bytes
        self.max_symbols_per_file = max_symbols_per_file
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.symbol_batch_size = symbol_batch_size
        
        self.file_builder = FileGraphBuilder(
            repo_id=repo_id,
            commit_sha=commit_sha,
            max_symbols=max_symbols_per_file,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        
        # Chunked extractor for large files
        self.chunked_extractor = ChunkedSymbolExtractor(
            batch_size=symbol_batch_size,
            force_gc_interval=5,
        )
        
    def build(self) -> RepoGraphResult:
        """Build the complete knowledge graph for the repository.
        
        Walks the repository tree, creates FileNode entries for all directories
        and files, delegates file parsing to FileGraphBuilder, and aggregates
        all results into a unified graph.
        
        Returns:
            RepoGraphResult containing the root node, all nodes, all edges,
            and indexing statistics.
            
        Raises:
            FileNotFoundError: If the repository root does not exist.
            ValueError: If the repository root is not a directory.
        """
        if not self.repo_root.exists():
            raise FileNotFoundError(f"Repository root does not exist: {self.repo_root}")
        if not self.repo_root.is_dir():
            raise ValueError(f"Repository root is not a directory: {self.repo_root}")
        
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []
        stats = IndexingStats()
        next_node_id = 0
        
        # Create root dir node
        root_file_node = FileNode(
            basename = self.repo_root.name or "root",
            relative_path = ".",
        )
        root_kg_node = KnowledgeGraphNode(
            node_id = str(next_node_id),
            node = root_file_node,
        )
        nodes.append(root_kg_node)
        next_node_id += 1
        stats.total_directories += 1
        
        # Build the graph recursively
        next_node_id = self._build_directory_graph(
            dir_path=self.repo_root,
            parent_kg_node=root_kg_node,
            next_node_id=next_node_id,
            nodes=nodes,
            edges=edges,
            stats=stats,
        )
        
        logger.info(
            f"Finished building repo graph: "
            f"{stats.indexed_files} files indexed, "
            f"{stats.total_symbols} symbols, "
            f"{stats.total_text_chunks} text chunks, "
            f"{stats.large_files_chunked} large files (chunked), "
            f"{stats.skipped_files} skipped, "
            f"{stats.failed_files} failed"
        )
        
        return RepoGraphResult(
            root_node=root_kg_node,
            nodes=nodes,
            edges=edges,
            stats=stats,
        )
        
    def _build_directory_graph(
        self,
        dir_path: Path,
        parent_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        stats: IndexingStats,
    ) -> int:
        """Recursively build the knowledge graph for a directory.
        
        Args:
            dir_path: Path to the directory to process.
            parent_kg_node: The parent KnowledgeGraphNode (directory).
            next_node_id: The next available node ID.
            nodes: List to append new nodes to.
            edges: List to append new edges to.
            stats: Statistics object to update.
            
        Returns:
            The next available node ID after processing.
        """
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError as e:
            logger.warning(f"Permission denied accessing {dir_path}: {e}")
            stats.errors.append(f"Permission denied accessing {dir_path}")
            return next_node_id
        except OSError as e:
            logger.warning(f"Error accessing directory {dir_path}: {e}")
            stats.errors.append(f"Error accessing directory {dir_path}: {e}")
            return next_node_id
        
        for entry in entries:
            # Skip excluded entries
            if self._should_exclude(entry):
                if entry.is_file():
                    stats.skipped_files += 1
                continue
            
            # Compute relative path
            relative_path = self._compute_relative_path(entry)
            
            if entry.is_dir():
                next_node_id = self._process_directory_entry(
                    entry=entry,
                    relative_path=relative_path,
                    parent_kg_node=parent_kg_node,
                    next_node_id=next_node_id,
                    nodes=nodes,
                    edges=edges,
                    stats=stats,
                )
            elif entry.is_file():
                stats.total_files += 1
                
                # Validate file and determine processing strategy
                validation_result = self._validate_and_prepare_file(entry, stats)
                if validation_result is None:
                    continue
                
                is_large_file = validation_result
                
                # Create file node and edge
                next_node_id, file_kg_node = self._create_file_node(
                    entry=entry,
                    relative_path=relative_path,
                    parent_kg_node=parent_kg_node,
                    next_node_id=next_node_id,
                    nodes=nodes,
                    edges=edges,
                )
                
                # Build file-specific graph (symbols, text chunks)
                if is_large_file:
                    next_node_id = self._process_large_file(
                        file_path=entry,
                        file_kg_node=file_kg_node,
                        next_node_id=next_node_id,
                        nodes=nodes,
                        edges=edges,
                        stats=stats,
                    )
                else:
                    # Normal processing for regular-sized files
                    next_node_id = self._process_regular_file(
                        file_path=entry,
                        file_kg_node=file_kg_node,
                        next_node_id=next_node_id,
                        nodes=nodes,
                        edges=edges,
                        stats=stats,
                    )
                    
        return next_node_id
    
    def _compute_relative_path(self, entry: Path) -> str:
        """Compute relative path from repo root with fallback handling.
        
        Args:
            entry: The file or directory entry to compute path for.
            
        Returns:
            Relative path string, or entry name if relative_to fails.
        """
        try:
            return str(entry.relative_to(self.repo_root))
        except ValueError:
            return entry.name
    
    def _process_directory_entry(
        self,
        entry: Path,
        relative_path: str,
        parent_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        stats: IndexingStats,
    ) -> int:
        """Process a directory entry: create node, edge, and recurse.
        
        Args:
            entry: The directory entry to process.
            relative_path: Relative path of the directory.
            parent_kg_node: The parent KnowledgeGraphNode (directory).
            next_node_id: The next available node ID.
            nodes: List to append new nodes to.
            edges: List to append new edges to.
            stats: Statistics object to update.
            
        Returns:
            The next available node ID after processing.
        """
        # Create directory node
        dir_file_node = FileNode(
            basename=entry.name,
            relative_path=relative_path
        )
        dir_kg_node = KnowledgeGraphNode(
            node_id=str(next_node_id),
            node=dir_file_node
        )
        nodes.append(dir_kg_node)
        next_node_id += 1
        stats.total_directories += 1
        
        # Create HAS_FILE edge from parent to this directory
        edges.append(KnowledgeGraphEdge(
            source_node=parent_kg_node,
            target_node=dir_kg_node,
            edge_type=KnowledgeGraphEdgeType.has_file,
        ))
        
        # Recursively build the graph for this directory
        next_node_id = self._build_directory_graph(
            dir_path=entry,
            parent_kg_node=dir_kg_node,
            next_node_id=next_node_id,
            nodes=nodes,
            edges=edges,
            stats=stats,
        )
        
        return next_node_id
    
    def _validate_and_prepare_file(
        self,
        entry: Path,
        stats: IndexingStats,
    ) -> bool | None:
        """Validate file and determine if it should be processed.
        
        Performs file size checks and support checks. Updates stats for skipped files.
        
        Args:
            entry: The file entry to validate.
            stats: Statistics object to update.
            
        Returns:
            True if file is large (needs chunked processing),
            False if file is regular-sized,
            None if file should be skipped.
        """
        # Check file size for processing strategy
        try:
            file_size = entry.stat().st_size
        except OSError:
            stats.skipped_files += 1
            return None
        
        # Skip files that exceed the absolute maximum
        if file_size > self.max_absolute_file_size_bytes:
            logger.warning(
                f"Skipping extremely large file {entry}: "
                f"{file_size} bytes > {self.max_absolute_file_size_bytes} bytes (hard limit)"
            )
            stats.skipped_files += 1
            return None
        
        # Determine if file is "large" (needs chunked processing)
        is_large_file = file_size > self.max_file_size_bytes
        
        # Skip unsupported files
        if not self.file_builder.support_file(entry):
            stats.skipped_files += 1
            return None
        
        return is_large_file
    
    def _create_file_node(
        self,
        entry: Path,
        relative_path: str,
        parent_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
    ) -> tuple[int, KnowledgeGraphNode]:
        """Create a file node and HAS_FILE edge.
        
        Args:
            entry: The file entry to create node for.
            relative_path: Relative path of the file.
            parent_kg_node: The parent KnowledgeGraphNode (directory).
            next_node_id: The next available node ID.
            nodes: List to append new nodes to.
            edges: List to append new edges to.
            
        Returns:
            Tuple of (next_node_id, file_kg_node) after creating the node.
        """
        # Create file FileNode
        file_node = FileNode(
            basename=entry.name,
            relative_path=relative_path,
        )
        file_kg_node = KnowledgeGraphNode(
            node_id=str(next_node_id),
            node=file_node,
        )
        nodes.append(file_kg_node)
        next_node_id += 1
        
        # Create HAS_FILE edge from parent directory to this file
        edges.append(KnowledgeGraphEdge(
            source_node=parent_kg_node,
            target_node=file_kg_node,
            edge_type=KnowledgeGraphEdgeType.has_file,
        ))
        
        return next_node_id, file_kg_node
    
    def _process_large_file(
        self,
        file_path: Path,
        file_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        stats: IndexingStats,
    ) -> int:
        """Process a large file using chunked extraction.
        
        Args:
            file_path: Path to the large file to process.
            file_kg_node: The KnowledgeGraphNode for the file.
            next_node_id: The next available node ID.
            nodes: List to append symbol nodes to.
            edges: List to append edges to.
            stats: Statistics object to update.
            
        Returns:
            The next available node ID after processing.
        """
        # Use chunked extraction for large files
        logger.info(
            f"Processing large file with chunked extraction: {file_path} "
            f"({file_path.stat().st_size} bytes)"
        )
        try:
            next_node_id = self._process_large_file_chunked(
                file_path=file_path,
                file_kg_node=file_kg_node,
                next_node_id=next_node_id,
                nodes=nodes,
                edges=edges,
                stats=stats,
            )
            stats.indexed_files += 1
            stats.large_files_chunked += 1
            return next_node_id
        except Exception as e:
            logger.error(f"Failed to process large file {file_path}: {e}")
            stats.failed_files += 1
            stats.errors.append(f"Failed to parse large file {file_path}: {e}")
            raise
    
    def _process_regular_file(
        self,
        file_path: Path,
        file_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        stats: IndexingStats,
    ) -> int:
        """Process a regular file using the FileGraphBuilder.
        
        Args:
            file_path: Path to the file to process.
            file_kg_node: The KnowledgeGraphNode for the file.
            next_node_id: The next available node ID.
            nodes: List to append new nodes to.
            edges: List to append new edges to.
            stats: Statistics object to update.
            
        Returns:
            The next available node ID after processing.
        """
        try:
            next_node_id, file_nodes, file_edges = self.file_builder.build_file_graph(
                parent_node=file_kg_node,
                file_path=file_path,
                next_node_id=next_node_id,
            )
            nodes.extend(file_nodes)
            edges.extend(file_edges)
            stats.indexed_files += 1
            
            # Update symbol/text chunk counts
            for node in file_nodes:
                if isinstance(node.node, SymbolNode):
                    stats.total_symbols += 1
                elif isinstance(node.node, TextNode):
                    stats.total_text_chunks += 1
        except Exception as e:
            logger.error(f"Failed to build graph for file {file_path}: {e}")
            stats.failed_files += 1
            stats.errors.append(f"Failed to parse {file_path}: {e}")
            raise
        finally:
            # Force garbage collection after processing regular file
            gc.collect()
        
        return next_node_id
    
    def _process_large_file_chunked(
        self,
        file_path: Path,
        file_kg_node: KnowledgeGraphNode,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        stats: IndexingStats,
    ) -> int:
        """Process a large file using chunked symbol extraction.
        
        This method uses the ChunkedSymbolExtractor to process large files
        in memory-bounded batches. Each batch of symbols is added to the
        nodes and edges lists immediately, and memory is released after
        each batch.
        
        On failure, partially-added nodes and edges are rolled back to ensure
        consistency. This prevents ID corruption where some nodes are added
        but the caller's next_node_id isn't updated.
        
        Args:
            file_path: Path to the large file to process.
            file_kg_node: The KnowledgeGraphNode for the file.
            next_node_id: The next available node ID.
            nodes: List to append symbol nodes to.
            edges: List to append edges to.
            stats: Statistics object to update.
            
        Returns:
            The next available node ID after processing.
            
        Raises:
            Exception: Re-raises any exception after rolling back partial changes.
        """
        batch_count = 0
        symbol_count = 0
        
        # Track initial state for rollback on failure
        initial_nodes_count = len(nodes)
        initial_edges_count = len(edges)
        initial_batches_processed = stats.symbol_batches_processed
        
        try:
            for batch in self.chunked_extractor.extract_symbols_chunked(
                file_path=file_path,
                parent_kg_node=file_kg_node,
                repo_id=self.repo_id,
                commit_sha=self.commit_sha,
                next_node_id=next_node_id,
            ):
                # Add batch nodes and edges
                nodes.extend(batch.nodes)
                edges.extend(batch.edges)
                
                # Update counters
                symbol_count += batch.symbols_in_batch
                batch_count += 1
                stats.symbol_batches_processed += 1
                
                # Update next_node_id based on symbols in this batch
                next_node_id += len(batch.nodes)
                
                logger.debug(
                    f"Processed batch {batch.batch_number} from {file_path.name}: "
                    f"{batch.symbols_in_batch} symbols"
                )
            
            # Update total symbols count
            stats.total_symbols += symbol_count
            
            logger.info(
                f"Completed chunked extraction for {file_path.name}: "
                f"{symbol_count} symbols in {batch_count} batches"
            )
            
        except Exception as e:
            # Rollback: remove any partially-added nodes and edges
            # This ensures the caller's next_node_id remains valid
            nodes_added = len(nodes) - initial_nodes_count
            edges_added = len(edges) - initial_edges_count
            
            if nodes_added > 0:
                del nodes[initial_nodes_count:]
            if edges_added > 0:
                del edges[initial_edges_count:]
            
            # Rollback stats
            stats.symbol_batches_processed = initial_batches_processed
            
            logger.error(
                f"Error during chunked extraction of {file_path}: {e}. "
                f"Rolled back {nodes_added} nodes and {edges_added} edges."
            )
            raise
        finally:
            # Force garbage collection after processing large file
            gc.collect()
        
        return next_node_id
    
    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded based on name and path.
        
        Args:
            path: The path to check.
            
        Returns:
            True if the path should be excluded, False otherwise.
        """
        name = path.name.lower()
        
        # Check if directory should be excluded
        if path.is_dir():
            if name in self.excluded_dirs:
                return True
            # Also check for pattern matches like "*.egg-info"
            for pattern in self.excluded_dirs:
                if "*" in pattern:
                    import fnmatch
                    if fnmatch.fnmatch(name, pattern):
                        return True
            return False
        
        # Check if file should be excluded
        if path.is_file():
            if name in self.excluded_files:
                return True
            # Skip hidden files (starting with .)
            if name.startswith(".") and name not in {".env", ".envrc"}:
                return True
            return False
        
        return False
    
    def build_for_paths(self, file_paths: Sequence[Path]) -> RepoGraphResult:
        """Build a knowledge graph for specific files only.
        
        This is useful for incremental indexing where only certain files
        have changed and need to be re-indexed.
        
        Args:
            file_paths: List of file paths (relative to repo_root) to index.
            
        Returns:
            RepoGraphResult containing nodes and edges for the specified files.
        """
        nodes: list[KnowledgeGraphNode] = []
        edges: list[KnowledgeGraphEdge] = []
        stats = IndexingStats()
        next_node_id = 0
        
        # Track created directory nodes to avoid duplicates
        dir_nodes: dict[str, KnowledgeGraphNode] = {}
        
        # Create root node
        root_file_node = FileNode(
            basename = self.repo_root.name or "root",
            relative_path = ".",
        )
        root_kg_node = KnowledgeGraphNode(
            node_id = str(next_node_id),
            node = root_file_node,
        )
        nodes.append(root_kg_node)
        dir_nodes["."] = root_kg_node
        next_node_id += 1
        
        for file_path in file_paths:
            # Resolve to absolute path
            abs_path = self.repo_root / file_path
            if not abs_path.exists():
                logger.warning(f"File does not exist: {abs_path}")
                stats.skipped_files += 1
                continue
            
            if not abs_path.is_file():
                continue
            
            stats.total_files += 1
            relative_path = str(file_path)
            
            # Ensure parent directories exist in the graph
            parent_kg_node = self._ensure_directory_chain(
                relative_path=relative_path,
                next_node_id=next_node_id,
                nodes=nodes,
                edges=edges,
                dir_nodes=dir_nodes,
            )
            
            next_node_id = len(nodes)  # Update based on added directory nodes
            
            # Validate file and determine processing strategy
            validation_result = self._validate_and_prepare_file(abs_path, stats)
            if validation_result is None:
                continue
            
            is_large_file = validation_result
            
            # Create file node and edge
            next_node_id, file_kg_node = self._create_file_node(
                entry=abs_path,
                relative_path=relative_path,
                parent_kg_node=parent_kg_node,
                next_node_id=next_node_id,
                nodes=nodes,
                edges=edges,
            )
            
            # Build file graph
            if is_large_file:
                # Use chunked extraction for large files
                logger.info(f"Processing large file with chunked extraction: {abs_path}")
                try:
                    next_node_id = self._process_large_file(
                        file_path=abs_path,
                        file_kg_node=file_kg_node,
                        next_node_id=next_node_id,
                        nodes=nodes,
                        edges=edges,
                        stats=stats,
                    )
                except Exception as e:
                    logger.error(f"Failed to process large file {abs_path}: {e}")
                    stats.failed_files += 1
                    stats.errors.append(f"Failed to parse large file {relative_path}: {e}")
            else:
                try:
                    next_node_id = self._process_regular_file(
                        file_path=abs_path,
                        file_kg_node=file_kg_node,
                        next_node_id=next_node_id,
                        nodes=nodes,
                        edges=edges,
                        stats=stats,
                    )
                except Exception as e:
                    logger.error(f"Failed to build graph for file {abs_path}: {e}")
                    stats.failed_files += 1
                    stats.errors.append(f"Failed to parse {relative_path}: {e}")
        
        return RepoGraphResult(
            root_node=root_kg_node,
            nodes=nodes,
            edges=edges,
            stats=stats,
        )
        
    def _ensure_directory_chain(
        self,
        relative_path: str,
        next_node_id: int,
        nodes: list[KnowledgeGraphNode],
        edges: list[KnowledgeGraphEdge],
        dir_nodes: dict[str, KnowledgeGraphNode],
    ) -> KnowledgeGraphNode:
        """Ensure all parent directories exist in the graph for a file path.
        
        Creates any missing directory nodes and HAS_FILE edges.
        
        Args:
            relative_path: The relative path of the file.
            next_node_id: The next available node ID.
            nodes: List to append new directory nodes to.
            edges: List to append new edges to.
            dir_nodes: Dictionary mapping relative paths to directory nodes.
            
        Returns:
            The KnowledgeGraphNode for the immediate parent directory.
        """
        parts = Path(relative_path).parts[:-1]  # Exclude filename
        current_path = "."
        parent_node = dir_nodes["."]
        
        for part in parts:
            child_path = str(Path(current_path) / part) if current_path != "." else part
            
            if child_path not in dir_nodes:
                # Create directory node
                dir_file_node = FileNode(
                    basename=part,
                    relative_path=child_path,
                )
                dir_kg_node = KnowledgeGraphNode(
                    node_id=str(len(nodes)),
                    node=dir_file_node,
                )
                nodes.append(dir_kg_node)
                dir_nodes[child_path] = dir_kg_node
                
                # Create HAS_FILE edge
                edges.append(KnowledgeGraphEdge(
                    source_node=parent_node,
                    target_node=dir_kg_node,
                    edge_type=KnowledgeGraphEdgeType.has_file,
                ))
            
            parent_node = dir_nodes[child_path]
            current_path = child_path
        
        return parent_node