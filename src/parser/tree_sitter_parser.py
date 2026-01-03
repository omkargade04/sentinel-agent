"""
Tree-sitter-based code parsing module.

This module provides functionality to parse source code files using tree-sitter,
supporting multiple programming languages. It handles file type detection and
parsing operations, returning a syntax tree representation of the source code.

The module uses tree-sitter parsers from the tree_sitter_languages package
and supports various common programming languages including Python, Java,
JavaScript, C++, Rust, Ruby, TypeScript and others.
"""

from typing import Tuple
from tree_sitter_language_pack import get_parser as get_ts_parser
from tree_sitter import Tree
from src.parser.file_types import FileTypes
from pathlib import Path

FILE_TYPE_TO_LANG = {
    FileTypes.PYTHON: "python",
    FileTypes.JAVASCRIPT: "javascript",
    FileTypes.TYPESCRIPT: "typescript",
    FileTypes.JAVA: "java",
    FileTypes.C: "c",
    FileTypes.CPP: "cpp",
    FileTypes.CSHARP: "csharp",
    FileTypes.GO: "go",
    FileTypes.RUBY: "ruby",
    FileTypes.RUST: "rust",
    FileTypes.SQL: "sql",
    FileTypes.KOTLIN: "kotlin",
    FileTypes.PHP: "php",
    FileTypes.HTML: "html",
    FileTypes.PROPERTIES: "properties",
    FileTypes.YAML: "yaml",
    FileTypes.XML: "xml",
    FileTypes.BASH: "bash",
    FileTypes.DOCKERFILE: "dockerfile",
}

def support_file(file: Path) -> bool:
    """Check if the file is supported by tree-sitter."""
    file_type = FileTypes.from_path(file)
    return file_type in FILE_TYPE_TO_LANG

class ParseError(Exception):
    """Exception raised when parsing a file fails."""
    pass


class UnsupportedLanguageError(Exception):
    """Exception raised when a file's language is not supported."""
    pass


def get_parser(file: Path) -> Tuple[Tree, str]:
    """Get the tree-sitter parser for the file and parse it.
    
    Args:
        file: Path to the source file to parse.
        
    Returns:
        Tuple of (parsed Tree-sitter Tree, language string).
        
    Raises:
        UnsupportedLanguageError: If the file type is not supported.
        ParseError: If the file cannot be read or parsed.
        FileNotFoundError: If the file does not exist.
    """
    if not file.exists():
        raise FileNotFoundError(f"File not found: {file}")
    
    file_type = FileTypes.from_path(file)
    lang = FILE_TYPE_TO_LANG.get(file_type)
    
    if lang is None:
        raise UnsupportedLanguageError(
            f"Unsupported file type for tree-sitter parsing: {file.suffix}"
        )
    
    try:
        lang_parser = get_ts_parser(lang)
        with file.open('rb') as f:
            tree = lang_parser.parse(f.read())
            return tree, lang
    except Exception as e:
        raise ParseError(f"Failed to parse file {file}: {e}") from e