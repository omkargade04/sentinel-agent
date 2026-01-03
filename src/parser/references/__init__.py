"""
Reference extraction module for cross-file analysis.

This package provides language-specific extractors for:
  - Import statements (for IMPORTS edges)
  - Call sites (for CALLS edges)

Supported languages:
  - Python
  - JavaScript
  - TypeScript

Usage:
    from src.parser.references import get_reference_extractor
    
    # Get extractor for a language
    extractor = get_reference_extractor("python")
    
    # Parse file with tree-sitter first
    from src.parser.tree_sitter_parser import get_parser
    tree, lang = get_parser(file_path)
    
    # Extract references
    with open(file_path, 'rb') as f:
        content = f.read()
    result = extractor.extract(tree, content)
    
    # Use the extracted references
    for imp in result.imports:
        print(f"Import: {imp.module_path} -> {imp.imported_names}")
    
    for call in result.call_sites:
        print(f"Call: {call.receiver}.{call.callee_name}() at line {call.line_number}")

Factory function:
    get_reference_extractor(language: str) -> ReferenceExtractor
        Returns the appropriate extractor for the given language.
        Raises ValueError for unsupported languages.
"""

from .base import (
    CallSite,
    ExtractionResult,
    ImportReference,
    ReferenceExtractor,
)
from .javascript_references import (
    JavaScriptReferenceExtractor,
    TypeScriptReferenceExtractor,
)
from .python_references import PythonReferenceExtractor

# Registry of language -> extractor class
_EXTRACTORS: dict[str, type[ReferenceExtractor]] = {
    "python": PythonReferenceExtractor,
    "javascript": JavaScriptReferenceExtractor,
    "typescript": TypeScriptReferenceExtractor,
}


def get_reference_extractor(language: str) -> ReferenceExtractor:
    """Get the reference extractor for the specified language.
    
    Args:
        language: Language identifier ("python", "javascript", "typescript")
        
    Returns:
        Instance of the appropriate ReferenceExtractor subclass
        
    Raises:
        ValueError: If the language is not supported
        
    Example:
        extractor = get_reference_extractor("python")
        result = extractor.extract(tree, file_content)
    """
    extractor_class = _EXTRACTORS.get(language)
    if extractor_class is None:
        supported = ", ".join(sorted(_EXTRACTORS.keys()))
        raise ValueError(
            f"Unsupported language for reference extraction: {language}. "
            f"Supported languages: {supported}"
        )
    return extractor_class()


# Public API
__all__ = [
    # Data models
    "ImportReference",
    "CallSite",
    "ExtractionResult",
    # Base class
    "ReferenceExtractor",
    # Concrete extractors
    "PythonReferenceExtractor",
    "JavaScriptReferenceExtractor",
    "TypeScriptReferenceExtractor",
    # Factory function
    "get_reference_extractor",
]

