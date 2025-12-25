# Parser Module

This module provides source code parsing capabilities for the AI Code Reviewer using Tree-sitter.

## Overview

The parser module is responsible for:
1. Parsing source code files into Abstract Syntax Trees (ASTs)
2. Extracting code symbols (classes, functions, methods) from ASTs
3. Building fingerprints for cross-commit symbol identity

## Architecture

```
parser/
├── __init__.py           # Module exports
├── file_types.py         # FileTypes enum for language detection
├── tree_sitter_parser.py # Tree-sitter parsing interface
├── symbol_extractor.py   # Language-specific symbol extraction
└── README.md             # This file
```

## Key Components

### FileTypes (`file_types.py`)

An enum mapping file extensions to supported languages:

```python
from src.parser.file_types import FileTypes

file_type = FileTypes.from_path(Path("example.py"))  # Returns FileTypes.PYTHON
```

### Tree-sitter Parser (`tree_sitter_parser.py`)

Provides the interface to Tree-sitter for parsing source files:

```python
from src.parser.tree_sitter_parser import get_parser, support_file

# Check if a file is supported
if support_file(Path("example.py")):
    tree, language = get_parser(Path("example.py"))
    # tree: Tree-sitter syntax tree
    # language: string like "python", "javascript", etc.
```

**Exceptions:**
- `UnsupportedLanguageError`: File type not supported by Tree-sitter
- `ParseError`: Failed to parse the file
- `FileNotFoundError`: File does not exist

### Symbol Extractor (`symbol_extractor.py`)

Language-specific extraction of code symbols from Tree-sitter ASTs:

```python
from src.parser.symbol_extractor import get_symbol_extractor, ExtractedSymbol

# Get a language-specific extractor
extractor = get_symbol_extractor("python")

# Extract symbols from a parsed tree
symbols: list[ExtractedSymbol] = extractor.extract_symbols(tree, file_path, file_content)

# Build parent-child hierarchy
hierarchy = extractor.build_symbol_hierarchy(symbols)
```

**Supported Languages:**
- Python (`PythonSymbolExtractor`)
- JavaScript/TypeScript (`JavaScriptSymbolExtractor`)

**Exceptions:**
- `SymbolExtractionError`: Failed to extract symbols
- `HierarchyBuildError`: Failed to build symbol hierarchy

## Design Decisions

### Why bytes instead of str for file content?

Tree-sitter is a C-based parser that operates on byte offsets. The `start_byte` and 
`end_byte` attributes in Tree-sitter nodes are byte positions, not character positions.
For files containing multi-byte UTF-8 characters (emoji, non-ASCII text), byte offset 
differs from character offset. Using bytes ensures correct span extraction.

### Why ephemeral ASTs?

We don't store raw AST nodes in the knowledge graph. Tree-sitter is used ephemerally 
to extract higher-level `SymbolNode` objects with stable identities. This reduces 
storage overhead and focuses the graph on semantically meaningful code units.

### Symbol Identity

Extracted symbols include data for generating two types of IDs:
- **symbol_version_id**: Snapshot-scoped ID using path + span (for hunk mapping)
- **stable_symbol_id**: Cross-snapshot ID using fingerprint (for historical linking)

The fingerprint is generated from the AST node type structure, making it resilient to
whitespace changes, formatting, and minor edits.

## Tree-sitter Node Types

Common node types used in symbol extraction:

| Language | Node Type | Description |
|----------|-----------|-------------|
| Python | `class_definition` | Class declaration |
| Python | `function_definition` | Function or method |
| Python | `block` | Indented code body |
| Python | `expression_statement` | Statement containing an expression |
| Python | `string` | String literal (including docstrings) |
| JavaScript | `class_declaration` | ES6 class |
| JavaScript | `function_declaration` | Function declaration |
| JavaScript | `method_definition` | Method in class body |
| JavaScript | `arrow_function` | Arrow function expression |
| JavaScript | `variable_declarator` | Variable binding |

## Adding New Languages

1. Add the file extension mapping in `FILE_TYPE_TO_LANG` in `tree_sitter_parser.py`
2. Create a new `LanguageSymbolExtractor` class in `symbol_extractor.py`:

```python
class GoSymbolExtractor(SymbolExtractor):
    @property
    def language(self) -> str:
        return "go"
    
    def extract_symbols(self, tree, file_path, file_content) -> list[ExtractedSymbol]:
        # Implement Go-specific extraction
        ...
```

3. Register in `_EXTRACTORS` dictionary in `symbol_extractor.py`

## Testing

```bash
# Run parser tests
pytest tests/parser/ -v

# Test with a specific file
python -c "
from src.parser.tree_sitter_parser import get_parser
from src.parser.symbol_extractor import get_symbol_extractor
from pathlib import Path

tree, lang = get_parser(Path('example.py'))
extractor = get_symbol_extractor(lang)
symbols = extractor.extract_symbols(tree, Path('example.py'), Path('example.py').read_bytes())
for s in symbols:
    print(f'{s.kind}: {s.name} ({s.start_line}-{s.end_line})')
"
```

## References

- [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/)
- [Python Grammar](https://github.com/tree-sitter/tree-sitter-python)
- [JavaScript Grammar](https://github.com/tree-sitter/tree-sitter-javascript)
- [TypeScript Grammar](https://github.com/tree-sitter/tree-sitter-typescript)
