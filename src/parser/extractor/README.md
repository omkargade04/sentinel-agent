# Symbol Extractor Module

## What

The extractor module provides language-specific symbol extraction from Tree-sitter ASTs. It extracts code symbols (functions, classes, methods, etc.) and builds hierarchical relationships between them.

## Why

Symbol extraction is fundamental for:
- **Code Understanding**: Identify semantic units (functions, classes) in code
- **Knowledge Graph Construction**: Create SymbolNode entries for graph
- **PR Analysis**: Map code changes to affected symbols
- **Cross-Language Support**: Extensible architecture for multiple languages

## How

### Architecture

```
parser/extractor/
├── base_extractor.py         # Abstract base class and data models
├── python_extractor.py       # Python-specific extraction
├── javascript_extractor.py   # JavaScript/TypeScript extraction
├── chunked_extractor.py      # Memory-efficient batch extraction
├── exceptions.py             # Custom exceptions
└── README.md               # This file
```

### Key Components

#### 1. Base Extractor (`base_extractor.py`)

**Purpose**: Defines abstract interface and shared data models.

**Key Classes**:

- `SymbolExtractor`: Abstract base class
  ```python
  class SymbolExtractor(ABC):
      @property
      @abstractmethod
      def language(self) -> str: ...
      
      @abstractmethod
      def extract_symbols(...) -> list[ExtractedSymbol]: ...
      
      @abstractmethod
      def build_symbol_hierarchy(...) -> list[SymbolHierarchy]: ...
  ```

- `ExtractedSymbol`: Symbol data model
  ```python
  @dataclass
  class ExtractedSymbol:
      kind: str              # "function", "class", "method"
      name: str              # Symbol name
      qualified_name: str    # Fully qualified name
      start_line: int        # Start line number
      end_line: int          # End line number
      start_byte: int        # Start byte offset
      end_byte: int          # End byte offset
      signature: str         # Function signature
      docstring: str         # Docstring if available
      parent: Optional[str] # Parent symbol name
  ```

- `SymbolHierarchy`: Parent-child relationships
  ```python
  @dataclass
  class SymbolHierarchy:
      parent: ExtractedSymbol
      child: ExtractedSymbol
  ```

#### 2. Language-Specific Extractors

**PythonExtractor** (`python_extractor.py`):
- Extracts: `class_definition`, `function_definition`
- Handles: Nested classes, methods, decorators
- Builds qualified names: `module.Class.method`

**JavaScriptExtractor** (`javascript_extractor.py`):
- Extracts: `class_declaration`, `function_declaration`, `method_definition`
- Handles: Arrow functions, ES6 classes, object methods
- Builds qualified names: `Class.method` or `functionName`

#### 3. Chunked Extractor (`chunked_extractor.py`)

**Purpose**: Memory-efficient extraction for large files.

**Key Features**:
- Processes symbols in batches
- Yields batches for immediate persistence
- Triggers GC periodically to manage memory
- Prevents memory issues with very large files

**Usage**:
```python
extractor = ChunkedSymbolExtractor(batch_size=50)
for batch in extractor.extract_symbols_chunked(...):
    # Persist batch to Neo4j
    await persist_batch(batch)
    # Memory automatically released
```

### Factory Pattern

**Factory Function** (`__init__.py`):
```python
from src.parser.extractor import get_symbol_extractor

extractor = get_symbol_extractor("python")
symbols = extractor.extract_symbols(tree, file_path, file_content)
```

**Supported Languages**:
- `python` → `PythonExtractor`
- `javascript` → `JavaScriptExtractor`
- `typescript` → `JavaScriptExtractor` (shared implementation)

### Extraction Flow

```
┌─────────────────────────────────────────────────────────┐
│              Symbol Extraction Pipeline                   │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. Parse file with Tree-sitter → AST                   │
│           ↓                                             │
│  2. Get language-specific extractor                    │
│           ↓                                             │
│  3. Traverse AST nodes                                  │
│     ├── Identify symbol nodes (class, function, etc.)  │
│     ├── Extract name, signature, docstring            │
│     ├── Calculate line/byte spans                      │
│     └── Build qualified names                          │
│           ↓                                             │
│  4. Build symbol hierarchy                             │
│     ├── Identify parent-child relationships            │
│     └── Create SymbolHierarchy entries                 │
│           ↓                                             │
│  5. Return ExtractedSymbol list                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Tree-sitter Node Types

**Python**:
- `class_definition`: Class declarations
- `function_definition`: Function/method definitions
- `decorated_definition`: Decorated functions/classes
- `block`: Code body blocks

**JavaScript**:
- `class_declaration`: ES6 class declarations
- `function_declaration`: Function declarations
- `method_definition`: Class methods
- `arrow_function`: Arrow function expressions

### Symbol Identity

**Qualified Names**:
- Python: `module.ClassName.method_name`
- JavaScript: `ClassName.methodName` or `functionName`

**Span Information**:
- `start_line` / `end_line`: For PR hunk mapping
- `start_byte` / `end_byte`: For precise code extraction

### Error Handling

**Custom Exceptions** (`exceptions.py`):
- `SymbolExtractionError`: Extraction failures
- `HierarchyBuildError`: Hierarchy construction failures
- `UnsupportedLanguageError`: Language not supported

### Usage Examples

**Basic Extraction**:
```python
from src.parser.tree_sitter_parser import get_parser
from src.parser.extractor import get_symbol_extractor
from pathlib import Path

file_path = Path("example.py")
tree, language = get_parser(file_path)
extractor = get_symbol_extractor(language)

file_content = file_path.read_bytes()
symbols = extractor.extract_symbols(tree, file_path, file_content)

for symbol in symbols:
    print(f"{symbol.kind}: {symbol.name} ({symbol.start_line}-{symbol.end_line})")
```

**Hierarchy Building**:
```python
hierarchy = extractor.build_symbol_hierarchy(symbols)
for parent_child in hierarchy:
    print(f"{parent_child.parent.name} contains {parent_child.child.name}")
```

**Chunked Extraction**:
```python
from src.parser.extractor import ChunkedSymbolExtractor

extractor = ChunkedSymbolExtractor(batch_size=50)
for batch in extractor.extract_symbols_chunked(
    file_path, parent_node, repo_id, commit_sha, next_node_id
):
    # Process batch
    nodes, edges = batch.to_kg_nodes_and_edges()
    await persist_to_neo4j(nodes, edges)
```

### Adding New Languages

1. **Create Extractor Class**:
```python
# extractor/go_extractor.py
from .base_extractor import SymbolExtractor, ExtractedSymbol

class GoSymbolExtractor(SymbolExtractor):
    @property
    def language(self) -> str:
        return "go"
    
    def extract_symbols(...) -> list[ExtractedSymbol]:
        # Implement Go-specific extraction
        ...
```

2. **Register Extractor**:
```python
# extractor/__init__.py
from .go_extractor import GoSymbolExtractor

_EXTRACTORS["go"] = GoSymbolExtractor
```

3. **Add Language Support**:
```python
# parser/tree_sitter_parser.py
FILE_TYPE_TO_LANG[".go"] = "go"
```

### Design Decisions

1. **Modular Architecture**: Each language has own extractor file
2. **Factory Pattern**: Centralized access via `get_symbol_extractor()`
3. **Byte-Based Spans**: Uses byte offsets for UTF-8 compatibility
4. **Qualified Names**: Enables cross-file symbol references
5. **Hierarchy Building**: Separates extraction from relationship building

### Dependencies

- **tree-sitter**: For AST parsing
- **dataclasses**: For data models
- **abc**: For abstract base classes
- **typing**: For type hints

### Testing

```python
# Test Python extraction
def test_python_extractor():
    extractor = PythonSymbolExtractor()
    tree, _ = get_parser(Path("test.py"))
    symbols = extractor.extract_symbols(tree, Path("test.py"), b"def foo(): pass")
    assert len(symbols) == 1
    assert symbols[0].name == "foo"

# Test hierarchy building
def test_hierarchy():
    extractor = PythonSymbolExtractor()
    symbols = [class_symbol, method_symbol]
    hierarchy = extractor.build_symbol_hierarchy(symbols)
    assert len(hierarchy) == 1
    assert hierarchy[0].parent.name == "MyClass"
    assert hierarchy[0].child.name == "my_method"
```

### Future Enhancements

- [ ] More languages (Go, Rust, Java, etc.)
- [ ] Type information extraction
- [ ] Import/export relationship detection
- [ ] Call graph construction
- [ ] Symbol renaming detection
- [ ] Documentation generation from symbols

