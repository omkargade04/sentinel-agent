"""
File Snippet Extractor Service

Production-grade service for extracting code snippets from cloned repositories.
Handles file system operations, path resolution, and line range extraction safely.
"""

import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
import chardet
import mimetypes
import re

logger = logging.getLogger(__name__)


@dataclass
class SnippetExtractionResult:
    """Result of code snippet extraction."""

    content: str
    file_path: str
    start_line: int
    end_line: int
    actual_lines: int
    file_size_bytes: int
    encoding: Optional[str] = None
    extraction_success: bool = True
    extraction_error: Optional[str] = None
    is_truncated: bool = False
    is_binary: bool = False


class FileSnippetExtractor:
    """
    Production-grade file snippet extractor.

    Safely extracts code snippets from cloned repositories with:
    - Path traversal protection
    - Binary file detection
    - Encoding detection and handling
    - Line range validation
    - Performance optimization for large files
    """

    # File extensions commonly used in code
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.cpp', '.c', '.h', '.hpp',
        '.cs', '.php', '.rb', '.go', '.rs', '.kt', '.scala', '.swift', '.m', '.mm',
        '.sql', '.r', '.R', '.sh', '.bash', '.ps1', '.yaml', '.yml', '.json',
        '.xml', '.html', '.css', '.scss', '.less', '.md', '.txt', '.toml', '.ini'
    }

    # Binary file patterns to avoid
    BINARY_EXTENSIONS = {
        '.exe', '.dll', '.so', '.dylib', '.bin', '.dat', '.db', '.sqlite',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.pdf', '.zip',
        '.tar', '.gz', '.7z', '.rar', '.mp3', '.mp4', '.avi', '.mov'
    }

    def __init__(
        self,
        max_file_size_mb: float = 10.0,
        max_line_length: int = 10000,
        encoding_detection_limit: int = 8192
    ):
        """
        Initialize file snippet extractor.

        Args:
            max_file_size_mb: Maximum file size to process (MB)
            max_line_length: Maximum line length to consider
            encoding_detection_limit: Bytes to read for encoding detection
        """
        self.max_file_size_bytes = int(max_file_size_mb * 1024 * 1024)
        self.max_line_length = max_line_length
        self.encoding_detection_limit = encoding_detection_limit

    def extract_snippet(
        self,
        clone_path: str,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None
    ) -> SnippetExtractionResult:
        """
        Extract code snippet from file in cloned repository.

        Args:
            clone_path: Path to cloned repository
            file_path: Relative file path within repository
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed, inclusive)
            max_lines: Maximum lines to extract (if no end_line)

        Returns:
            SnippetExtractionResult with extracted content or error info
        """
        try:
            # Step 1: Resolve and validate file path
            resolved_path = self._resolve_file_path(clone_path, file_path)
            if not resolved_path:
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0, file_size_bytes=0,
                    extraction_success=False,
                    extraction_error=f"File not found or path traversal detected: {file_path}"
                )

            # Step 2: Check file properties
            file_info = self._get_file_info(resolved_path)
            if not file_info['is_valid']:
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0,
                    file_size_bytes=file_info['size'],
                    extraction_success=False,
                    extraction_error=file_info['error'],
                    is_binary=file_info['is_binary']
                )

            # Step 3: Determine encoding
            encoding = self._detect_encoding(resolved_path)
            if not encoding:
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0,
                    file_size_bytes=file_info['size'],
                    extraction_success=False,
                    extraction_error="Could not detect file encoding"
                )

            # Step 4: Extract content
            return self._extract_file_content(
                resolved_path, file_path, start_line, end_line, max_lines,
                encoding, file_info['size']
            )

        except Exception as e:
            logger.error(f"Unexpected error extracting snippet from {file_path}: {e}")
            return SnippetExtractionResult(
                content="", file_path=file_path, start_line=start_line or 1,
                end_line=end_line or 1, actual_lines=0, file_size_bytes=0,
                extraction_success=False,
                extraction_error=f"Extraction failed: {str(e)}"
            )

    def extract_multiple_snippets(
        self,
        clone_path: str,
        candidates: List[Dict[str, Any]]
    ) -> List[SnippetExtractionResult]:
        """
        Extract multiple code snippets efficiently with file content caching.

        Args:
            clone_path: Path to cloned repository
            candidates: List of candidate dicts with file_path, start_line, end_line

        Returns:
            List of SnippetExtractionResult objects in same order as input candidates
        """
        # Initialize results array to preserve order
        results = [None] * len(candidates)

        # Group candidates by file for efficient processing
        files_to_candidates = {}
        for i, candidate in enumerate(candidates):
            file_path = candidate.get('file_path', '')
            if file_path not in files_to_candidates:
                files_to_candidates[file_path] = []
            files_to_candidates[file_path].append((i, candidate))

        logger.info(f"Extracting snippets from {len(files_to_candidates)} files for {len(candidates)} candidates")

        # Cache for file contents to avoid re-reading same files
        file_cache = {}

        # Process each file once and cache content
        for file_path, file_candidates in files_to_candidates.items():
            # Extract snippets for all candidates from this file using cached content
            for original_idx, candidate in file_candidates:
                result = self._extract_snippet_with_cache(
                    clone_path=clone_path,
                    file_path=file_path,
                    start_line=candidate.get('start_line'),
                    end_line=candidate.get('end_line'),
                    file_cache=file_cache
                )
                # Place result at original candidate position
                results[original_idx] = result

        success_count = sum(1 for r in results if r and r.extraction_success)
        logger.info(f"Snippet extraction completed: {success_count}/{len(results)} successful")

        return results

    def _extract_snippet_with_cache(
        self,
        clone_path: str,
        file_path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_lines: Optional[int] = None,
        file_cache: Optional[Dict] = None
    ) -> SnippetExtractionResult:
        """
        Extract code snippet with file content caching for performance.

        Args:
            clone_path: Path to cloned repository
            file_path: Relative file path within repository
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed, inclusive)
            max_lines: Maximum lines to extract (if no end_line)
            file_cache: Dictionary to cache file contents

        Returns:
            SnippetExtractionResult with extracted content or error info
        """
        if file_cache is None:
            # Fall back to regular extraction without caching
            return self.extract_snippet(clone_path, file_path, start_line, end_line, max_lines)

        try:
            # Step 1: Check if file is already cached
            cache_key = file_path
            if cache_key in file_cache:
                cached_data = file_cache[cache_key]
                if cached_data['success']:
                    return self._extract_from_cached_content(
                        cached_data['lines'], file_path, start_line, end_line, max_lines,
                        cached_data['encoding'], cached_data['file_size']
                    )
                else:
                    # File had an error when cached, return same error
                    return SnippetExtractionResult(
                        content="", file_path=file_path, start_line=start_line or 1,
                        end_line=end_line or 1, actual_lines=0, file_size_bytes=0,
                        extraction_success=False, extraction_error=cached_data['error']
                    )

            # Step 2: File not cached, resolve and validate path
            resolved_path = self._resolve_file_path(clone_path, file_path)
            if not resolved_path:
                error_msg = f"File not found or path traversal detected: {file_path}"
                file_cache[cache_key] = {'success': False, 'error': error_msg}
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0, file_size_bytes=0,
                    extraction_success=False, extraction_error=error_msg
                )

            # Step 3: Validate file properties
            file_info = self._get_file_info(resolved_path)
            if not file_info['is_valid']:
                file_cache[cache_key] = {'success': False, 'error': file_info['error']}
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0,
                    file_size_bytes=file_info['size'],
                    extraction_success=False, extraction_error=file_info['error'],
                    is_binary=file_info['is_binary']
                )

            # Step 4: Detect encoding
            encoding = self._detect_encoding(resolved_path)
            if not encoding:
                error_msg = "Could not detect file encoding"
                file_cache[cache_key] = {'success': False, 'error': error_msg}
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0,
                    file_size_bytes=file_info['size'],
                    extraction_success=False, extraction_error=error_msg
                )

            # Step 5: Read file content and cache it
            try:
                with open(resolved_path, 'r', encoding=encoding, errors='replace') as f:
                    lines = f.readlines()

                # Validate line lengths if max_line_length is set
                if self.max_line_length > 0:
                    validated_lines = []
                    for line_num, line in enumerate(lines, 1):
                        if len(line) > self.max_line_length:
                            logger.warning(f"Line {line_num} in {file_path} exceeds max length ({len(line)} > {self.max_line_length})")
                            # Truncate the line with indication
                            truncated_line = line[:self.max_line_length-20] + "... [line truncated]\n"
                            validated_lines.append(truncated_line)
                        else:
                            validated_lines.append(line)
                    lines = validated_lines

                # Cache successful read
                file_cache[cache_key] = {
                    'success': True,
                    'lines': lines,
                    'encoding': encoding,
                    'file_size': file_info['size'],
                    'total_lines': len(lines)
                }

                return self._extract_from_cached_content(
                    lines, file_path, start_line, end_line, max_lines,
                    encoding, file_info['size']
                )

            except UnicodeDecodeError as e:
                error_msg = f"Encoding error: {str(e)}"
                file_cache[cache_key] = {'success': False, 'error': error_msg}
                return SnippetExtractionResult(
                    content="", file_path=file_path, start_line=start_line or 1,
                    end_line=end_line or 1, actual_lines=0,
                    file_size_bytes=file_info['size'],
                    extraction_success=False, extraction_error=error_msg
                )

        except Exception as e:
            logger.error(f"Unexpected error extracting cached snippet from {file_path}: {e}")
            return SnippetExtractionResult(
                content="", file_path=file_path, start_line=start_line or 1,
                end_line=end_line or 1, actual_lines=0, file_size_bytes=0,
                extraction_success=False,
                extraction_error=f"Extraction failed: {str(e)}"
            )

    def _extract_from_cached_content(
        self,
        lines: List[str],
        file_path: str,
        start_line: Optional[int],
        end_line: Optional[int],
        max_lines: Optional[int],
        encoding: str,
        file_size: int
    ) -> SnippetExtractionResult:
        """Extract content from already-cached file lines."""
        total_lines = len(lines)

        # Determine line range
        if start_line is None:
            start_line = 1
        if end_line is None:
            if max_lines:
                end_line = min(start_line + max_lines - 1, total_lines)
            else:
                end_line = min(start_line + 50, total_lines)  # Default to 50 lines

        # Validate and adjust line numbers (1-indexed to 0-indexed)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, end_line)

        if start_idx >= total_lines:
            return SnippetExtractionResult(
                content="", file_path=file_path,
                start_line=start_line, end_line=end_line,
                actual_lines=0, file_size_bytes=file_size,
                encoding=encoding, extraction_success=False,
                extraction_error=f"Start line {start_line} exceeds file length {total_lines}"
            )

        # Extract lines
        extracted_lines = lines[start_idx:end_idx]
        content = ''.join(extracted_lines)

        # Check if content was truncated
        actual_end = start_line + len(extracted_lines) - 1
        is_truncated = actual_end < end_line

        return SnippetExtractionResult(
            content=content,
            file_path=file_path,
            start_line=start_line,
            end_line=actual_end,
            actual_lines=len(extracted_lines),
            file_size_bytes=file_size,
            encoding=encoding,
            extraction_success=True,
            is_truncated=is_truncated
        )

    def _resolve_file_path(self, clone_path: str, file_path: str) -> Optional[Path]:
        try:
            clone_path_obj = Path(clone_path).resolve()

            # Normalize the file path (remove leading slash, ./, etc.)
            file_path = file_path.lstrip('/')
            file_path = re.sub(r'^\./', '', file_path)

            # Join paths safely
            target_path = (clone_path_obj / file_path).resolve()

            # Ensure target is within clone directory
            if not str(target_path).startswith(str(clone_path_obj)):
                logger.warning(f"Path traversal detected: {file_path}")
                return None

            # Check if file exists
            if not target_path.exists():
                logger.debug(f"File not found: {target_path}")
                return None

            if not target_path.is_file():
                logger.debug(f"Path is not a file: {target_path}")
                return None

            return target_path

        except Exception as e:
            logger.error(f"Error resolving file path {file_path}: {e}")
            return None

    def _get_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Get file information and validate it's processable."""
        try:
            stat = file_path.stat()
            file_size = stat.st_size

            # Check file size
            if file_size > self.max_file_size_bytes:
                return {
                    'is_valid': False,
                    'error': f"File too large: {file_size / (1024*1024):.1f}MB > {self.max_file_size_bytes / (1024*1024):.1f}MB",
                    'size': file_size,
                    'is_binary': False
                }

            # Check if likely binary based on extension
            extension = file_path.suffix.lower()
            if extension in self.BINARY_EXTENSIONS:
                return {
                    'is_valid': False,
                    'error': f"Binary file type: {extension}",
                    'size': file_size,
                    'is_binary': True
                }

            # Quick binary detection by reading first chunk
            is_binary = self._is_binary_file(file_path)
            if is_binary:
                return {
                    'is_valid': False,
                    'error': "Binary file detected",
                    'size': file_size,
                    'is_binary': True
                }

            return {
                'is_valid': True,
                'size': file_size,
                'is_binary': False,
                'error': None
            }

        except Exception as e:
            return {
                'is_valid': False,
                'error': f"File stat error: {str(e)}",
                'size': 0,
                'is_binary': False
            }

    def _is_binary_file(self, file_path: Path, chunk_size: int = 1024) -> bool:
        """Quick binary file detection."""
        try:
            with open(file_path, 'rb') as f:
                chunk = f.read(chunk_size)
                return b'\x00' in chunk  # Null bytes indicate binary
        except Exception:
            return True  # Assume binary if can't read

    def _detect_encoding(self, file_path: Path) -> Optional[str]:
        """Detect file encoding."""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(self.encoding_detection_limit)

            # Try UTF-8 first (most common for code)
            try:
                raw_data.decode('utf-8')
                return 'utf-8'
            except UnicodeDecodeError:
                pass

            # Use chardet for other encodings
            detection = chardet.detect(raw_data)
            encoding = detection.get('encoding')
            confidence = detection.get('confidence', 0)

            # Only trust high-confidence detections
            if encoding and confidence > 0.7:
                return encoding

            # Fallback to utf-8 with error handling
            return 'utf-8'

        except Exception as e:
            logger.debug(f"Encoding detection error for {file_path}: {e}")
            return 'utf-8'  # Default fallback

    def _extract_file_content(
        self,
        file_path: Path,
        original_file_path: str,
        start_line: Optional[int],
        end_line: Optional[int],
        max_lines: Optional[int],
        encoding: str,
        file_size: int
    ) -> SnippetExtractionResult:
        """Extract actual file content with line range."""
        try:
            # Read file with encoding
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                lines = f.readlines()

            # Validate line lengths if max_line_length is set
            if self.max_line_length > 0:
                validated_lines = []
                for line_num, line in enumerate(lines, 1):
                    if len(line) > self.max_line_length:
                        logger.warning(f"Line {line_num} in {original_file_path} exceeds max length ({len(line)} > {self.max_line_length})")
                        # Truncate the line with indication
                        truncated_line = line[:self.max_line_length-20] + "... [line truncated]\n"
                        validated_lines.append(truncated_line)
                    else:
                        validated_lines.append(line)
                lines = validated_lines

            total_lines = len(lines)

            # Determine line range
            if start_line is None:
                start_line = 1
            if end_line is None:
                if max_lines:
                    end_line = min(start_line + max_lines - 1, total_lines)
                else:
                    end_line = min(start_line + 50, total_lines)  # Default to 50 lines

            # Validate and adjust line numbers (1-indexed to 0-indexed)
            start_idx = max(0, start_line - 1)
            end_idx = min(total_lines, end_line)

            if start_idx >= total_lines:
                return SnippetExtractionResult(
                    content="", file_path=original_file_path,
                    start_line=start_line, end_line=end_line,
                    actual_lines=0, file_size_bytes=file_size,
                    encoding=encoding, extraction_success=False,
                    extraction_error=f"Start line {start_line} exceeds file length {total_lines}"
                )

            # Extract lines
            extracted_lines = lines[start_idx:end_idx]
            content = ''.join(extracted_lines)

            # Check if content was truncated
            actual_end = start_line + len(extracted_lines) - 1
            is_truncated = actual_end < end_line

            return SnippetExtractionResult(
                content=content,
                file_path=original_file_path,
                start_line=start_line,
                end_line=actual_end,
                actual_lines=len(extracted_lines),
                file_size_bytes=file_size,
                encoding=encoding,
                extraction_success=True,
                is_truncated=is_truncated
            )

        except UnicodeDecodeError as e:
            return SnippetExtractionResult(
                content="", file_path=original_file_path,
                start_line=start_line or 1, end_line=end_line or 1,
                actual_lines=0, file_size_bytes=file_size,
                extraction_success=False,
                extraction_error=f"Encoding error: {str(e)}"
            )

        except Exception as e:
            return SnippetExtractionResult(
                content="", file_path=original_file_path,
                start_line=start_line or 1, end_line=end_line or 1,
                actual_lines=0, file_size_bytes=file_size,
                extraction_success=False,
                extraction_error=f"File read error: {str(e)}"
            )