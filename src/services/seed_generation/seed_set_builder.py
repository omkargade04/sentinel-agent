"""
Seed Set Builder Service

Orchestrates the complete pipeline for generating seed sets from PR diff hunks:
1. For each changed file, read content from cloned repo
2. Parse with Tree-sitter to extract symbols
3. Find symbols overlapping with changed lines in hunks
4. Convert to SeedSymbol/SeedFile models
5. Return complete SeedSetS0 object

This is the main entry point for seed set generation.: AST Analysis
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from src.parser import tree_sitter_parser
from src.parser.tree_sitter_parser import ParseError, UnsupportedLanguageError
from src.parser.file_types import FileTypes
from src.parser.extractor import (
    get_symbol_extractor,
    get_supported_languages,
    ExtractedSymbol,
    SymbolExtractionError,
)
from src.models.schemas.pr_review.pr_patch import PRFilePatch, ChangeType
from src.models.schemas.pr_review.seed_set import (
    SeedSetS0,
    SeedSymbol,
    SeedFile,
    SeedFileReason,
    SymbolKind,
)
from src.services.seed_generation.overlap_detector import (
    OverlapDetector,
    SymbolOverlap,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Mapping from extractor kind strings to SymbolKind enum
KIND_MAPPING: Dict[str, SymbolKind] = {
    "function": SymbolKind.FUNCTION,
    "method": SymbolKind.METHOD,
    "class": SymbolKind.CLASS,
    "interface": SymbolKind.INTERFACE,
    "enum": SymbolKind.ENUM,
    "struct": SymbolKind.STRUCT,
    "constant": SymbolKind.CONSTANT,
    "variable": SymbolKind.VARIABLE,
    "property": SymbolKind.PROPERTY,
    "constructor": SymbolKind.CONSTRUCTOR,
}

@dataclass
class BuildStats:
    """Statistics from seed set building proccess"""
    files_processed: int = 0
    files_with_symbols: int = 0
    files_skipped: int = 0
    total_symbols_extracted: int = 0
    total_symbols_overlapping: int = 0
    parse_errors: int = 0
    unsupported_languages: int = 0
    
    
class SeedSetBuilder:
    """
    Builds SeedSetS0 from PR patches by analyzing AST and detecting overlaps.
    
    The builder:
    1. Iterates through all changed files in the PR
    2. For supported languages, parses and extracts symbols
    3. Finds symbols that overlap with changed lines
    4. Converts to SeedSymbol objects with hunk associations
    5. Creates SeedFile entries for unsupported/failed files
    
    Usage:
        builder = SeedSetBuilder(clone_path="/tmp/pr-clone-xyz")
        seed_set = builder.build_seed_set(patches)
    """
    
    def __init__(
        self,
        clone_path: str,
        max_file_size_bytes: int = 1_000_000,
        max_symbols_per_file: int = 200,
        min_overlap_ratio: float = 0.0,
    ):
        """
        Initialize the seed set builder.
        
        Args:
            clone_path: Path to the cloned PR head repository
            max_file_size_bytes: Maximum file size to process (skip larger files)
            max_symbols_per_file: Maximum symbols to extract per file
            min_overlap_ratio: Minimum overlap ratio for symbol inclusion
        """
        self.clone_path = Path(clone_path)
        self.max_file_size_bytes = max_file_size_bytes
        self.max_symbols_per_file = max_symbols_per_file
        self.overlap_detector = OverlapDetector(min_overlap_ratio=min_overlap_ratio)
        self.logger = get_logger(__name__)
        
        # Track supported languages for symbol extraction
        self.supported_languages = set(get_supported_languages())
        
    def build_seed_set(self, patches: List[PRFilePatch]) -> Tuple[SeedSetS0, BuildStats]:
        """
        Build a complete seed set from PR patches.
        
        Args:
            patches: List of PRFilePatch objects from diff parsing
            
        Returns:
            Tuple of (SeedSetS0, BuildStats)
        """
        self.logger.info(f"Building seed set from {len(patches)} patches")
        
        seed_symbols: List[SeedSymbol] = []
        seed_files: List[SeedFile] = []
        stats = BuildStats()
        
        for patch in patches:
            stats.files_processed += 1
            
            # Handle deleted files
            # Use change_type_str to handle both enum and string values safely
            if patch.change_type_str == ChangeType.REMOVED.value:
                seed_files.append(SeedFile(
                    file_path=patch.file_path,
                    reason=SeedFileReason.FILE_DELETED,
                    change_type=patch.change_type_str,
                    language=self._detect_language(patch.file_path),
                ))
                stats.files_skipped += 1
                continue
            
            # Handle binary files
            if patch.binary_file:
                seed_files.append(SeedFile(
                    file_path=patch.file_path,
                    reason=SeedFileReason.BINARY_FILE,
                    change_type=patch.change_type_str,
                ))
                stats.files_skipped += 1
                continue
            
            # Handle files without hunks (no actual code changes)
            if not patch.hunks:
                seed_files.append(SeedFile(
                    file_path=patch.file_path,
                    reason=SeedFileReason.PATCH_MISSING,
                    change_type=patch.change_type_str,
                    language=self._detect_language(patch.file_path),
                ))
                stats.files_skipped += 1
                continue
            
            # Process the file
            result = self._process_file(patch)
            
            if result.symbols:
                seed_symbols.extend(result.symbols)
                stats.files_with_symbols += 1
                stats.total_symbols_overlapping += len(result.symbols)
                
            if result.seed_file:
                seed_files.append(result.seed_file)
                
            stats.total_symbols_extracted += result.total_extracted
            
            if result.error_type == "parse_error":
                stats.parse_errors += 1
            elif result.error_type == "unsupported":
                stats.unsupported_languages += 1
                
        #Build the final SeedSetS0 object
        seed_set = SeedSetS0(
            seed_symbols=seed_symbols,
            seed_files=seed_files,
            extraction_timestamp=datetime.now().isoformat(),
            ast_parser_version="tree-sitter-0.21",
        )
        
        self.logger.info(
            f"Built seed set: {len(seed_symbols)} symbols from "
            f"{stats.files_with_symbols} files, {len(seed_files)} seed files"
        )
        
        return seed_set, stats
    
    def _process_file(self, patch: PRFilePatch) -> "FileProcessResult":
        """
        Process a single file to extract overlapping symbols.
        
        Args:
            patch: The file patch to process
            
        Returns:
            FileProcessResult with symbols and/or seed file
        """
        file_path = patch.file_path
        full_path = self.clone_path / file_path
        
        # Check if file exists in clone
        if not full_path.exists():
            self.logger.warning(f"File not found in clone: {file_path}")
            return FileProcessResult(
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.PATCH_MISSING,
                    change_type=patch.change_type_str,
                    error_message="File not found in clone",
                )
            )
        
        # Check file size
        file_size = full_path.stat().st_size
        if file_size > self.max_file_size_bytes:
            self.logger.warning(
                f"File too large, skipping: {file_path} ({file_size} bytes)"
            )
            return FileProcessResult(
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.PARSE_ERROR,
                    change_type=patch.change_type_str,
                    error_message=f"File too large: {file_size} bytes",
                )
            )
            
        # Detect language and check support
        language = self._detect_language(file_path)
        
        if language not in self.supported_languages:
            return FileProcessResult(
                error_type="unsupported",
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.NO_SYMBOL_MATCH,
                    change_type=patch.change_type_str,
                    language=language,
                    line_count=patch.additions + patch.deletions,
                )
            )
            
        # Parse and extract symbols
        try:
            tree, language = tree_sitter_parser.get_parser(full_path)
            
            extractor = get_symbol_extractor(language)
            if not extractor:
                return FileProcessResult(
                    error_type="unsupported",
                    seed_file=SeedFile(
                        file_path=file_path,
                        reason=SeedFileReason.NO_SYMBOL_MATCH,
                        change_type=patch.change_type_str,
                        language=language,
                    )
                )
            
            # Read file content for extraction
            file_content = full_path.read_bytes()
            
            # Extract symbols
            extracted_symbols = extractor.extract_symbols(tree, full_path, file_content)
            
            # Limit symbols per file
            if len(extracted_symbols) > self.max_symbols_per_file:
                self.logger.warning(
                    f"Truncating symbols for {file_path}: "
                    f"{len(extracted_symbols)} -> {self.max_symbols_per_file}"
                )
                extracted_symbols = extracted_symbols[:self.max_symbols_per_file]
            
            total_extracted = len(extracted_symbols)
            
            # Find overlapping symbols
            overlaps = self.overlap_detector.find_overlapping_symbols(
                extracted_symbols, patch.hunks
            )
            
            if not overlaps:
                # File has symbols but none overlap with changes
                return FileProcessResult(
                    total_extracted=total_extracted,
                    seed_file=SeedFile(
                        file_path=file_path,
                        reason=SeedFileReason.NO_SYMBOL_MATCH,
                        change_type=patch.change_type_str,
                        language=language,
                        line_count=patch.additions + patch.deletions,
                    )
                )
                
            # Convert to SeedSymbol objects
            seed_symbols = [
                self._convert_to_seed_symbol(overlap, file_path, language)
                for overlap in overlaps
            ]
            
            return FileProcessResult(
                symbols=seed_symbols,
                total_extracted=total_extracted,
            )
            
        except UnsupportedLanguageError as e:
            self.logger.debug(f"Unsupported language for {file_path}: {e}")
            return FileProcessResult(
                error_type="unsupported",
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.NO_SYMBOL_MATCH,
                    change_type=patch.change_type_str,
                    language=language,
                )
            )
            
        except (ParseError, SymbolExtractionError) as e:
            self.logger.warning(f"Parse error for {file_path}: {e}")
            return FileProcessResult(
                error_type="parse_error",
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.PARSE_ERROR,
                    change_type=patch.change_type_str,
                    language=language,
                    error_message=str(e),
                )
            )
            
        except Exception as e:
            # Enhanced error logging with type information for debugging
            self.logger.error(
                f"Unexpected error processing {file_path}: {e}",
                extra={
                    "change_type": str(patch.change_type),
                    "change_type_type": type(patch.change_type).__name__,
                    "error_type": type(e).__name__,
                    "file_path": file_path,
                    "language": language,
                }
            )
            return FileProcessResult(
                error_type="parse_error",
                seed_file=SeedFile(
                    file_path=file_path,
                    reason=SeedFileReason.PARSE_ERROR,
                    change_type=patch.change_type_str,
                    language=language,
                    error_message=str(e),
                )
            )
        
    def _convert_to_seed_symbol(
        self,
        overlap: SymbolOverlap,
        file_path: str,
        language: str
    ) -> SeedSymbol:
        """
        Convert a SymbolOverlap to a SeedSymbol.
        
        Args:
            overlap: The overlap result from detection
            file_path: Relative file path
            language: Programming language
            
        Returns:
            SeedSymbol instance
        """
        symbol = overlap.symbol
        
        # Map kind string to SymbolKind enum
        kind = KIND_MAPPING.get(symbol.kind.lower(), SymbolKind.FUNCTION)
        
        return SeedSymbol(
            file_path=file_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            kind=kind,
            name=symbol.name,
            qualified_name=symbol.qualified_name,
            language=language,
            signature=symbol.signature if symbol.signature else None,
            docstring=symbol.docstring,
            hunk_ids=overlap.hunk_ids,
            fingerprint=self._generate_fingerprint(symbol),
        )
        
    def _generate_fingerprint(self, symbol: ExtractedSymbol) -> str:
        """
        Generate a fingerprint for symbol matching with Neo4j.
        
        Uses AST node types for structural fingerprinting.
        
        Args:
            symbol: The extracted symbol
            
        Returns:
            Fingerprint string
        """
        if symbol.node_types:
            # Use first N node types for fingerprint
            types_str = "_".join(symbol.node_types[:20])
            return f"{symbol.kind}_{symbol.name}_{hash(types_str) % 10**8}"
        return f"{symbol.kind}_{symbol.name}"
    
    def _detect_language(self, file_path: str) -> Optional[str]:
        """
        Detect programming language from file path.
        
        Args:
            file_path: Relative file path
            
        Returns:
            Language string or None
        """
        try:
            file_type = FileTypes.from_path(Path(file_path))
            if file_type != FileTypes.UNKNOWN:
                return file_type.value
        except Exception:
            pass
        return None
    
@dataclass
class FileProcessResult:
    """Result of processing a single file."""
    symbols: Optional[List[SeedSymbol]] = None
    seed_file: Optional[SeedFile] = None
    total_extracted: int = 0
    error_type: Optional[str] = None  # "parse_error", "unsupported", None
        