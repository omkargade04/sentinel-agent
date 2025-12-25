"""
Symbol Extractor Module

This module provides language-specific symbol extraction from Tree-sitter ASTs.
It extracts code symbols (functions, classes, methods, etc.) into a standardized
ExtractedSymbol format that can be used to build the Knowledge Graph.

Public API:
  - get_symbol_extractor(language): Factory function to get a language-specific extractor
  - get_supported_languages(): List of languages with extraction support
  - ExtractedSymbol: Dataclass representing an extracted code symbol
  - SymbolHierarchy: Dataclass representing parent-child relationships
  - SymbolExtractor: Abstract base class for language-specific extractors

Exceptions:
  - SymbolExtractionError: Raised when symbol extraction fails
  - HierarchyBuildError: Raised when building symbol hierarchy fails
  - UnsupportedLanguageError: Raised for unsupported languages

Usage:
    from src.parser.extractor import (
        get_symbol_extractor,
        get_supported_languages,
        ExtractedSymbol,
        SymbolHierarchy,
        SymbolExtractionError,
    )
    
    # Get extractor for a language
    extractor = get_symbol_extractor("python")
    if extractor is None:
        raise UnsupportedLanguageError("python", get_supported_languages())
    
    # Extract symbols from a Tree-sitter tree
    symbols = extractor.extract_symbols(tree, file_path, file_content)
    
    # Build hierarchy (parent-child relationships)
    hierarchy = extractor.build_symbol_hierarchy(symbols)

Adding a new language:
    1. Create a new file: `{language}_extractor.py`
    2. Implement a class that extends SymbolExtractor
    3. Register it in _EXTRACTORS below
    
See README.md for detailed documentation.
"""

from .base_extractor import (
    ExtractedSymbol,
    SymbolExtractor,
    SymbolHierarchy,
)
from .exceptions import (
    HierarchyBuildError,
    SymbolExtractionError,
    UnsupportedLanguageError,
)
from .javascript_extractor import (
    JavaScriptSymbolExtractor,
    TypeScriptSymbolExtractor,
)
from .python_extractor import PythonSymbolExtractor


# Registry of language-specific extractors
# Maps language identifier -> extractor class
_EXTRACTORS: dict[str, type[SymbolExtractor]] = {
    "python": PythonSymbolExtractor,
    "javascript": JavaScriptSymbolExtractor,
    "typescript": TypeScriptSymbolExtractor,
}


def get_symbol_extractor(language: str) -> SymbolExtractor | None:
    """Get a symbol extractor for the given language.
    
    This is the primary factory function for obtaining language-specific
    symbol extractors.
    
    Args:
        language: Language identifier (e.g., 'python', 'javascript', 'typescript')
        
    Returns:
        SymbolExtractor instance for the language, or None if not supported
        
    Example:
        extractor = get_symbol_extractor("python")
        if extractor:
            symbols = extractor.extract_symbols(tree, path, content)
    """
    extractor_class = _EXTRACTORS.get(language.lower())
    if extractor_class:
        return extractor_class()
    return None


def get_supported_languages() -> list[str]:
    """Get list of languages with symbol extraction support.
    
    Returns:
        List of language identifiers that can be passed to get_symbol_extractor()
        
    Example:
        if language not in get_supported_languages():
            print(f"Unsupported: {language}")
    """
    return list(_EXTRACTORS.keys())


def register_extractor(language: str, extractor_class: type[SymbolExtractor]) -> None:
    """Register a new symbol extractor for a language.
    
    This allows plugins or extensions to add support for additional languages
    without modifying this module directly.
    
    Args:
        language: Language identifier (will be lowercased)
        extractor_class: The SymbolExtractor subclass to register
        
    Example:
        from my_plugin import GoSymbolExtractor
        register_extractor("go", GoSymbolExtractor)
    """
    _EXTRACTORS[language.lower()] = extractor_class


# Public API exports
__all__ = [
    # Factory functions
    "get_symbol_extractor",
    "get_supported_languages",
    "register_extractor",
    # Data classes
    "ExtractedSymbol",
    "SymbolHierarchy",
    # Base class (for extension)
    "SymbolExtractor",
    # Concrete extractors (for direct use or extension)
    "PythonSymbolExtractor",
    "JavaScriptSymbolExtractor",
    "TypeScriptSymbolExtractor",
    # Exceptions
    "SymbolExtractionError",
    "HierarchyBuildError",
    "UnsupportedLanguageError",
]
