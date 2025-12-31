from dataclasses import dataclass, field

@dataclass
class IndexingStats:
    """Statistics collected during repository indexing.
    
    Attributes:
        total_files: Total number of files discovered.
        indexed_files: Number of files successfully indexed.
        skipped_files: Number of files skipped (unsupported or excluded).
        failed_files: Number of files that failed to parse.
        total_directories: Total number of directories.
        total_symbols: Total number of symbols extracted.
        total_text_chunks: Total number of text chunks created.
        large_files_chunked: Number of large files processed via chunking.
        symbol_batches_processed: Total number of symbol batches processed for large files.
        errors: List of error messages encountered during indexing.
    """
    total_files: int = 0
    indexed_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    total_directories: int = 0
    total_symbols: int = 0
    total_text_chunks: int = 0
    large_files_chunked: int = 0
    symbol_batches_processed: int = 0
    errors: list[str] = field(default_factory=list)