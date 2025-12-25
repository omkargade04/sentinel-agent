"""
Custom exceptions for symbol extraction.

This module defines all exceptions that can be raised during symbol extraction
and hierarchy building operations.
"""


class SymbolExtractionError(Exception):
    """Exception raised when symbol extraction fails.
    
    This can occur when:
      - Tree-sitter parsing encounters unexpected node structures
      - File content cannot be decoded properly
      - Recursion depth is exceeded during AST traversal
      - Any other unexpected error during symbol extraction
    
    Attributes:
        message: Explanation of the error
        language: The language being parsed (if available)
        file_path: The file being parsed (if available)
    """
    
    def __init__(
        self,
        message: str,
        language: str | None = None,
        file_path: str | None = None,
    ):
        self.message = message
        self.language = language
        self.file_path = file_path
        
        details = []
        if language:
            details.append(f"language={language}")
        if file_path:
            details.append(f"file={file_path}")
        
        full_message = message
        if details:
            full_message = f"{message} [{', '.join(details)}]"
        
        super().__init__(full_message)


class HierarchyBuildError(Exception):
    """Exception raised when building symbol hierarchy fails.
    
    This can occur when:
      - Symbol spans are invalid or inconsistent
      - The span-stack algorithm encounters an unexpected state
      - Memory or recursion limits are exceeded
    
    Attributes:
        message: Explanation of the error
        symbol_count: Number of symbols being processed (if available)
    """
    
    def __init__(
        self,
        message: str,
        symbol_count: int | None = None,
    ):
        self.message = message
        self.symbol_count = symbol_count
        
        full_message = message
        if symbol_count is not None:
            full_message = f"{message} [processing {symbol_count} symbols]"
        
        super().__init__(full_message)


class UnsupportedLanguageError(Exception):
    """Exception raised when attempting to extract symbols from an unsupported language.
    
    Attributes:
        language: The unsupported language identifier
        supported_languages: List of supported language identifiers
    """
    
    def __init__(
        self,
        language: str,
        supported_languages: list[str] | None = None,
    ):
        self.language = language
        self.supported_languages = supported_languages or []
        
        message = f"Unsupported language for symbol extraction: '{language}'"
        if self.supported_languages:
            message += f". Supported languages: {', '.join(self.supported_languages)}"
        
        super().__init__(message)
