# End-to-End Repository Parsing and Symbol Extraction Flow

This document provides a comprehensive explanation of how the repository parsing and symbol extraction system works, with a detailed example.

## Table of Contents
1. [High-Level Architecture](#high-level-architecture)
2. [Complete Flow Diagram](#complete-flow-diagram)
3. [Detailed Example Walkthrough](#detailed-example-walkthrough)
4. [Key Components Explained](#key-components-explained)
5. [Data Structures](#data-structures)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RepoParsingService                        │
│              (Entry Point - API Layer)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   RepoGraphBuilder                           │
│  • Walks directory tree                                      │
│  • Creates FileNode hierarchy                                │
│  • Delegates file processing to FileGraphBuilder             │
│  • Aggregates all nodes and edges                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
┌──────────────────┐        ┌──────────────────┐
│  Directories     │        │     Files         │
│  (FileNode)      │        │  (FileNode)       │
└──────────────────┘        └────────┬──────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  FileGraphBuilder    │
                          │  • Determines type   │
                          │  • Routes to parser  │
                          └──────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                  │
                    ▼                                  ▼
         ┌──────────────────────┐        ┌──────────────────────┐
         │   Code Files         │        │   Text Files         │
         │  (Python/JS/etc.)     │        │  (Markdown/TXT)       │
         └──────────┬───────────┘        └──────────┬───────────┘
                    │                                │
                    ▼                                ▼
         ┌──────────────────────┐        ┌──────────────────────┐
         │  Tree-sitter Parser  │        │  Text Chunker         │
         │  • Parses AST         │        │  • Splits text        │
         └──────────┬───────────┘        └──────────┬───────────┘
                    │                                │
                    ▼                                ▼
         ┌──────────────────────┐        ┌──────────────────────┐
         │  Symbol Extractor    │        │  TextNode Creation   │
         │  • Extracts symbols  │        │  • Creates chunks     │
         │  • Builds hierarchy  │        │  • Links chunks      │
         └──────────┬───────────┘        └──────────┬───────────┘
                    │                                │
                    └────────────┬───────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │  Knowledge Graph     │
                    │  • FileNodes         │
                    │  • SymbolNodes       │
                    │  • TextNodes         │
                    │  • Edges            │
                    └──────────────────────┘
```

---

## Complete Flow Diagram

```
START: parse_repository()
│
├─> 1. RepoParsingService.parse_repository()
│   │   Input: local_path="/tmp/repo-123", repo_id="repo-123", commit_sha="abc123"
│   │
│   └─> 2. RepoGraphBuilder.__init__()
│       │   • Creates FileGraphBuilder instance
│       │   • Creates ChunkedSymbolExtractor (for large files)
│       │
│       └─> 3. RepoGraphBuilder.build()
│           │
│           ├─> 3.1. Create root FileNode
│           │   • basename="repo-123"
│           │   • relative_path="."
│           │   • node_id="0"
│           │
│           └─> 3.2. _build_directory_graph(repo_root)
│               │   Recursive traversal starts here
│               │
│               ├─> 3.2.1. iterdir() → Get entries: [src/, README.md, .gitignore]
│               │   • Sorted: directories first, then files (alphabetically)
│               │
│               ├─> 3.2.2. Process each entry:
│               │
│               │   ├─> Entry: "src/" (directory)
│               │   │   └─> _process_directory_entry()
│               │   │       ├─> Create FileNode for "src/"
│               │   │       │   • basename="src"
│               │   │       │   • relative_path="src"
│               │   │       │   • node_id="1"
│               │   │       ├─> Create HAS_FILE edge: root → src/
│               │   │       └─> RECURSE: _build_directory_graph("src/")
│               │   │           │
│               │   │           ├─> iterdir() → [utils.py, models.py]
│               │   │           │
│               │   │           ├─> Entry: "utils.py" (file)
│               │   │           │   ├─> Create FileNode
│               │   │           │   │   • basename="utils.py"
│               │   │           │   │   • relative_path="src/utils.py"
│               │   │           │   │   • node_id="2"
│               │   │           │   ├─> Create HAS_FILE edge: src/ → utils.py
│               │   │           │   └─> _process_regular_file()
│               │   │           │       └─> FileGraphBuilder.build_file_graph()
│               │   │           │           │
│               │   │           │           ├─> Detect: Python file → _tree_sitter_file_graph()
│               │   │           │           │   │
│               │   │           │           │   ├─> tree_sitter_parser.get_parser()
│               │   │           │           │   │   • Detect language: "python"
│               │   │           │           │   │   • Parse file → Tree-sitter AST
│               │   │           │           │   │
│               │   │           │           │   ├─> get_symbol_extractor("python")
│               │   │           │           │   │   • Returns PythonSymbolExtractor instance
│               │   │           │           │   │
│               │   │           │           │   ├─> extractor.extract_symbols()
│               │   │           │           │   │   • Walk AST tree
│               │   │           │           │   │   • Find: class_definition, function_definition
│               │   │           │           │   │   • Extract: name, signature, docstring, spans
│               │   │           │           │   │   • Returns: [ExtractedSymbol, ...]
│               │   │           │           │   │
│               │   │           │           │   ├─> For each ExtractedSymbol:
│               │   │           │           │   │   ├─> Generate symbol_version_id
│               │   │           │           │   │   ├─> Generate stable_symbol_id
│               │   │           │           │   │   ├─> Generate fingerprint
│               │   │           │           │   │   └─> Create SymbolNode
│               │   │           │           │   │       • node_id="3", "4", ...
│               │   │           │           │   │
│               │   │           │           │   ├─> Create HAS_SYMBOL edges
│               │   │           │           │   │   • FileNode → SymbolNode (for each symbol)
│               │   │           │           │   │
│               │   │           │           │   └─> extractor.build_symbol_hierarchy()
│               │   │           │           │       • Determine parent-child relationships
│               │   │           │           │       • Create CONTAINS_SYMBOL edges
│               │   │           │           │       • Example: Class → Method
│               │   │           │           │
│               │   │           │           └─> Return: (next_node_id, symbol_nodes, edges)
│               │   │           │
│               │   │           └─> Entry: "models.py" (similar process)
│               │   │
│               │   ├─> Entry: "README.md" (file)
│               │   │   └─> _process_regular_file()
│               │   │       └─> FileGraphBuilder.build_file_graph()
│               │   │           └─> Detect: Markdown file → _text_file_graph()
│               │   │               │
│               │   │               ├─> Read file content
│               │   │               ├─> _split_text_into_chunks()
│               │   │               │   • Split into chunks of 1000 chars
│               │   │               │   • Overlap: 200 chars
│               │   │               │
│               │   │               ├─> For each chunk:
│               │   │               │   ├─> Create TextNode
│               │   │               │   │   • text="..."
│               │   │               │   │   • start_line=0, end_line=25
│               │   │               │   │   • node_id="10"
│               │   │               │   ├─> Create HAS_TEXT edge: FileNode → TextNode
│               │   │               │   └─> Create NEXT_CHUNK edge: TextNode → TextNode
│               │   │               │
│               │   │               └─> Return: (next_node_id, text_nodes, edges)
│               │   │
│               │   └─> Entry: ".gitignore" (file)
│               │       └─> _should_exclude() → True (hidden file)
│               │           └─> Skip
│               │
│               └─> 3.3. Return RepoGraphResult
│                   • root_node: FileNode (repo root)
│                   • nodes: [all FileNodes, SymbolNodes, TextNodes]
│                   • edges: [all HAS_FILE, HAS_SYMBOL, HAS_TEXT, CONTAINS_SYMBOL, NEXT_CHUNK]
│                   • stats: IndexingStats (counts, errors, etc.)
│
END: Return RepoGraphResult
```

---

## Detailed Example Walkthrough

Let's trace through a concrete example with a small Python repository.

### Example Repository Structure

```
/tmp/repo-123/
├── src/
│   ├── utils.py
│   └── models.py
├── README.md
└── .gitignore
```

### File Contents

**src/utils.py:**
```python
"""Utility functions for the application."""

def calculate_sum(a: int, b: int) -> int:
    """Add two numbers together.
    
    Args:
        a: First number
        b: Second number
    
    Returns:
        Sum of a and b
    """
    return a + b

class MathHelper:
    """Helper class for mathematical operations."""
    
    def multiply(self, x: float, y: float) -> float:
        """Multiply two numbers."""
        return x * y
    
    def divide(self, x: float, y: float) -> float:
        """Divide two numbers."""
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y
```

**src/models.py:**
```python
"""Data models for the application."""

class User:
    """Represents a user in the system."""
    
    def __init__(self, name: str, email: str):
        self.name = name
        self.email = email
```

**README.md:**
```markdown
# My Application

This is a simple Python application.

## Features

- Utility functions
- Data models
```

### Step-by-Step Execution

#### Step 1: Initialization

```python
# RepoParsingService.parse_repository() is called
repo_path = Path("/tmp/repo-123")
repo_id = "repo-123"
commit_sha = "abc123def456"

# Create RepoGraphBuilder
builder = RepoGraphBuilder(
    repo_id=repo_id,
    commit_sha=commit_sha,
    repo_root=repo_path
)
```

**What happens:**
- `RepoGraphBuilder.__init__()` creates:
  - `FileGraphBuilder` instance (for per-file processing)
  - `ChunkedSymbolExtractor` instance (for large files >1MB)

#### Step 2: Build Root Node

```python
# builder.build() is called
root_file_node = FileNode(
    basename="repo-123",  # or "root" if repo_root.name is empty
    relative_path="."
)
root_kg_node = KnowledgeGraphNode(
    node_id="0",
    node=root_file_node
)
nodes = [root_kg_node]  # node_id="0"
next_node_id = 1
```

**Graph State:**
```
Node 0: FileNode(basename="repo-123", relative_path=".")
```

#### Step 3: Process Root Directory

```python
# _build_directory_graph(repo_root="/tmp/repo-123")
entries = sorted(iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
# Result: [Path("src/"), Path("README.md"), Path(".gitignore")]
```

**Sorting explanation:**
- `not p.is_dir()`: `False` for directories (0), `True` for files (1)
- Directories come first (0 < 1)
- Within each group, sorted alphabetically by lowercase name

#### Step 4: Process "src/" Directory

```python
# Entry: Path("src/") - is_dir() == True
relative_path = "src"  # computed from repo_root

# Create directory FileNode
dir_file_node = FileNode(
    basename="src",
    relative_path="src"
)
dir_kg_node = KnowledgeGraphNode(
    node_id="1",
    node=dir_file_node
)
nodes.append(dir_kg_node)  # node_id="1"

# Create HAS_FILE edge
edges.append(KnowledgeGraphEdge(
    source_node=root_kg_node,  # node_id="0"
    target_node=dir_kg_node,   # node_id="1"
    edge_type=KnowledgeGraphEdgeType.has_file
))
```

**Graph State:**
```
Node 0: FileNode(basename="repo-123", relative_path=".")
Node 1: FileNode(basename="src", relative_path="src")

Edge: Node 0 --[HAS_FILE]--> Node 1
```

#### Step 5: Recurse into "src/" Directory

```python
# _build_directory_graph(dir_path="src/", parent_kg_node=dir_kg_node)
entries = sorted(iterdir(), ...)
# Result: [Path("utils.py"), Path("models.py")]
```

#### Step 6: Process "src/utils.py" File

```python
# Entry: Path("utils.py") - is_file() == True
relative_path = "src/utils.py"

# Create file FileNode
file_file_node = FileNode(
    basename="utils.py",
    relative_path="src/utils.py"
)
file_kg_node = KnowledgeGraphNode(
    node_id="2",
    node=file_file_node
)
nodes.append(file_kg_node)  # node_id="2"

# Create HAS_FILE edge
edges.append(KnowledgeGraphEdge(
    source_node=dir_kg_node,   # node_id="1" (src/)
    target_node=file_kg_node,  # node_id="2" (utils.py)
    edge_type=KnowledgeGraphEdgeType.has_file
))
```

**Graph State:**
```
Node 0: FileNode(basename="repo-123", relative_path=".")
Node 1: FileNode(basename="src", relative_path="src")
Node 2: FileNode(basename="utils.py", relative_path="src/utils.py")

Edge: Node 0 --[HAS_FILE]--> Node 1
Edge: Node 1 --[HAS_FILE]--> Node 2
```

#### Step 7: Extract Symbols from "src/utils.py"

```python
# FileGraphBuilder.build_file_graph() is called
# Detect: Python file → _tree_sitter_file_graph()

# Step 7.1: Parse with Tree-sitter
tree, language = tree_sitter_parser.get_parser(Path("src/utils.py"))
# Returns: (Tree-sitter AST tree, "python")

# Step 7.2: Get symbol extractor
extractor = get_symbol_extractor("python")
# Returns: PythonSymbolExtractor instance

# Step 7.3: Extract symbols
file_content = Path("src/utils.py").read_bytes()
extracted_symbols = extractor.extract_symbols(tree, file_path, file_content)
```

**What `extract_symbols()` does internally:**

```python
# PythonSymbolExtractor._walk_for_definitions() walks the AST:

# Found: function_definition at line 4
symbol1 = ExtractedSymbol(
    kind="function",
    name="calculate_sum",
    qualified_name="calculate_sum",  # top-level function
    start_line=4,
    end_line=13,
    start_byte=...,
    end_byte=...,
    signature="def calculate_sum(a: int, b: int) -> int:",
    docstring="Add two numbers together.\n\n    Args:\n        a: First number\n        b: Second number\n\n    Returns:\n        Sum of a and b",
    node_types=["function_definition", "block", ...],
    parent_index=-1  # top-level
)

# Found: class_definition at line 15
symbol2 = ExtractedSymbol(
    kind="class",
    name="MathHelper",
    qualified_name="MathHelper",
    start_line=15,
    end_line=27,
    signature="class MathHelper:",
    docstring="Helper class for mathematical operations.",
    parent_index=-1
)

# Found: function_definition inside class at line 17
symbol3 = ExtractedSymbol(
    kind="method",
    name="multiply",
    qualified_name="MathHelper.multiply",  # qualified name includes class
    start_line=17,
    end_line=19,
    signature="def multiply(self, x: float, y: float) -> float:",
    docstring="Multiply two numbers.",
    parent_index=1  # parent is MathHelper (index 1 in list)
)

# Found: function_definition inside class at line 21
symbol4 = ExtractedSymbol(
    kind="method",
    name="divide",
    qualified_name="MathHelper.divide",
    start_line=21,
    end_line=25,
    signature="def divide(self, x: float, y: float) -> float:",
    docstring="Divide two numbers.",
    parent_index=1  # parent is MathHelper
)

# Result: [symbol1, symbol2, symbol3, symbol4]
```

#### Step 8: Create SymbolNodes

```python
# For each ExtractedSymbol, create SymbolNode
symbol_nodes = []

for extracted in extracted_symbols:
    # Generate IDs
    symbol_version_id = generate_symbol_version_id(
        commit_sha="abc123def456",
        relative_path="src/utils.py",
        kind=extracted.kind,
        name=extracted.name,
        qualified_name=extracted.qualified_name,
        start_line=extracted.start_line,
        end_line=extracted.end_line
    )
    # Result: "abc123def456:src/utils.py:function:calculate_sum:4:13"
    
    stable_symbol_id = generate_stable_symbol_id(
        repo_id="repo-123",
        kind=extracted.kind,
        qualified_name=extracted.qualified_name,
        name=extracted.name,
        fingerprint=extracted.fingerprint
    )
    # Result: "repo-123:function:calculate_sum:<fingerprint>"
    
    # Create SymbolNode
    symbol_node = SymbolNode(
        symbol_version_id=symbol_version_id,
        stable_symbol_id=stable_symbol_id,
        kind=extracted.kind,
        name=extracted.name,
        qualified_name=extracted.qualified_name,
        language="python",
        relative_path="src/utils.py",
        start_line=extracted.start_line,
        end_line=extracted.end_line,
        signature=extracted.signature,
        docstring=extracted.docstring,
        fingerprint=extracted.fingerprint
    )
    
    # Wrap in KnowledgeGraphNode
    kg_node = KnowledgeGraphNode(
        node_id=str(next_node_id),  # "3", "4", "5", "6"
        node=symbol_node
    )
    symbol_nodes.append(kg_node)
    nodes.append(kg_node)
    next_node_id += 1
    
    # Create HAS_SYMBOL edge
    edges.append(KnowledgeGraphEdge(
        source_node=file_kg_node,  # node_id="2" (utils.py)
        target_node=kg_node,        # node_id="3", "4", "5", "6"
        edge_type=KnowledgeGraphEdgeType.has_symbol
    ))
```

**Graph State:**
```
Node 0: FileNode(basename="repo-123", relative_path=".")
Node 1: FileNode(basename="src", relative_path="src")
Node 2: FileNode(basename="utils.py", relative_path="src/utils.py")
Node 3: SymbolNode(kind="function", name="calculate_sum", ...)
Node 4: SymbolNode(kind="class", name="MathHelper", ...)
Node 5: SymbolNode(kind="method", name="multiply", ...)
Node 6: SymbolNode(kind="method", name="divide", ...)

Edge: Node 0 --[HAS_FILE]--> Node 1
Edge: Node 1 --[HAS_FILE]--> Node 2
Edge: Node 2 --[HAS_SYMBOL]--> Node 3
Edge: Node 2 --[HAS_SYMBOL]--> Node 4
Edge: Node 2 --[HAS_SYMBOL]--> Node 5
Edge: Node 2 --[HAS_SYMBOL]--> Node 6
```

#### Step 9: Build Symbol Hierarchy

```python
# Build parent-child relationships
hierarchy = extractor.build_symbol_hierarchy(extracted_symbols)
```

**How hierarchy building works:**

1. **Sort symbols** by (start_line ASC, end_line DESC):
   ```
   [symbol1 (4-13), symbol2 (15-27), symbol3 (17-19), symbol4 (21-25)]
   ```

2. **Use span-stack algorithm:**
   - Process symbol1 (calculate_sum): Stack=[], no parent → push to stack
   - Process symbol2 (MathHelper): Stack=[symbol1], symbol1 doesn't contain symbol2 → pop symbol1, push symbol2
   - Process symbol3 (multiply): Stack=[symbol2], symbol2 contains symbol3 → symbol2 is parent
   - Process symbol4 (divide): Stack=[symbol2, symbol3], symbol3 doesn't contain symbol4 → pop symbol3, symbol2 contains symbol4 → symbol2 is parent

3. **Result:**
   ```python
   hierarchy = [
       SymbolHierarchy(parent_index=1, child_index=2),  # MathHelper → multiply
       SymbolHierarchy(parent_index=1, child_index=3),  # MathHelper → divide
   ]
   ```

4. **Create CONTAINS_SYMBOL edges:**
   ```python
   for rel in hierarchy:
       edges.append(KnowledgeGraphEdge(
           source_node=symbol_nodes[rel.parent_index],  # Node 4 (MathHelper)
           target_node=symbol_nodes[rel.child_index],    # Node 5 (multiply), Node 6 (divide)
           edge_type=KnowledgeGraphEdgeType.contains_symbol
       ))
   ```

**Final Graph State for utils.py:**
```
Node 0: FileNode(basename="repo-123", relative_path=".")
Node 1: FileNode(basename="src", relative_path="src")
Node 2: FileNode(basename="utils.py", relative_path="src/utils.py")
Node 3: SymbolNode(kind="function", name="calculate_sum", start_line=4, end_line=13)
Node 4: SymbolNode(kind="class", name="MathHelper", start_line=15, end_line=27)
Node 5: SymbolNode(kind="method", name="multiply", start_line=17, end_line=19)
Node 6: SymbolNode(kind="method", name="divide", start_line=21, end_line=25)

Edge: Node 0 --[HAS_FILE]--> Node 1
Edge: Node 1 --[HAS_FILE]--> Node 2
Edge: Node 2 --[HAS_SYMBOL]--> Node 3
Edge: Node 2 --[HAS_SYMBOL]--> Node 4
Edge: Node 2 --[HAS_SYMBOL]--> Node 5
Edge: Node 2 --[HAS_SYMBOL]--> Node 6
Edge: Node 4 --[CONTAINS_SYMBOL]--> Node 5  (MathHelper contains multiply)
Edge: Node 4 --[CONTAINS_SYMBOL]--> Node 6  (MathHelper contains divide)
```

#### Step 10: Process "src/models.py" File

Similar process as utils.py:

```python
# Create FileNode for models.py
file_kg_node = KnowledgeGraphNode(node_id="7", node=FileNode(...))

# Extract symbols
# Found: class User
symbol_node = KnowledgeGraphNode(node_id="8", node=SymbolNode(...))

# Create edges
Edge: Node 1 --[HAS_FILE]--> Node 7
Edge: Node 7 --[HAS_SYMBOL]--> Node 8
```

#### Step 11: Process "README.md" File

```python
# Entry: Path("README.md") - is_file() == True
# FileGraphBuilder detects: Markdown file → _text_file_graph()

# Read content
content = "# My Application\n\nThis is a simple Python application.\n\n## Features\n\n- Utility functions\n- Data models"

# Split into chunks (chunk_size=1000, chunk_overlap=200)
chunks = _split_text_into_chunks(content)
# Result: [
#   "# My Application\n\nThis is a simple Python application.\n\n## Features\n\n- Utility functions\n- Data models"
# ]
# (File is small, so only one chunk)

# Create TextNode
text_node = TextNode(
    text=chunks[0],
    start_line=0,
    end_line=7  # Count newlines
)
text_kg_node = KnowledgeGraphNode(node_id="9", node=text_node)

# Create edges
Edge: Node 0 --[HAS_FILE]--> Node 10  (README.md FileNode)
Edge: Node 10 --[HAS_TEXT]--> Node 9   (TextNode)
```

#### Step 12: Skip ".gitignore"

```python
# Entry: Path(".gitignore")
if _should_exclude(entry):
    # Hidden file (starts with ".") → skip
    stats.skipped_files += 1
    continue
```

#### Step 13: Final Result

```python
return RepoGraphResult(
    root_node=root_kg_node,  # Node 0
    nodes=[
        # FileNodes
        Node 0: FileNode("repo-123", "."),
        Node 1: FileNode("src", "src"),
        Node 2: FileNode("utils.py", "src/utils.py"),
        Node 7: FileNode("models.py", "src/models.py"),
        Node 10: FileNode("README.md", "README.md"),
        
        # SymbolNodes
        Node 3: SymbolNode("calculate_sum", function, ...),
        Node 4: SymbolNode("MathHelper", class, ...),
        Node 5: SymbolNode("multiply", method, ...),
        Node 6: SymbolNode("divide", method, ...),
        Node 8: SymbolNode("User", class, ...),
        
        # TextNodes
        Node 9: TextNode(...),
    ],
    edges=[
        # Directory structure
        Edge: 0 --[HAS_FILE]--> 1,
        Edge: 1 --[HAS_FILE]--> 2,
        Edge: 1 --[HAS_FILE]--> 7,
        Edge: 0 --[HAS_FILE]--> 10,
        
        # Symbols
        Edge: 2 --[HAS_SYMBOL]--> 3,
        Edge: 2 --[HAS_SYMBOL]--> 4,
        Edge: 2 --[HAS_SYMBOL]--> 5,
        Edge: 2 --[HAS_SYMBOL]--> 6,
        Edge: 7 --[HAS_SYMBOL]--> 8,
        
        # Hierarchy
        Edge: 4 --[CONTAINS_SYMBOL]--> 5,
        Edge: 4 --[CONTAINS_SYMBOL]--> 6,
        
        # Text
        Edge: 10 --[HAS_TEXT]--> 9,
    ],
    stats=IndexingStats(
        indexed_files=3,
        total_symbols=5,
        total_text_chunks=1,
        skipped_files=1,
        ...
    )
)
```

---

## Key Components Explained

### 1. RepoGraphBuilder

**Purpose:** Orchestrates the entire repository parsing process.

**Key Methods:**
- `build()`: Entry point that creates root node and starts recursive traversal
- `_build_directory_graph()`: Recursively processes directories
- `_process_directory_entry()`: Creates directory nodes and recurses
- `_process_regular_file()`: Processes normal-sized files (<1MB)
- `_process_large_file()`: Processes large files (>1MB) using chunked extraction

**Exit Condition:** Recursion stops when `iterdir()` returns an empty list (no more entries in directory).

### 2. FileGraphBuilder

**Purpose:** Processes individual files and extracts symbols or text chunks.

**Key Methods:**
- `build_file_graph()`: Routes to appropriate handler based on file type
- `_tree_sitter_file_graph()`: Processes code files using Tree-sitter
- `_text_file_graph()`: Processes documentation files by chunking text

**File Type Detection:**
- Code files: Uses `tree_sitter_parser.support_file()` to check if Tree-sitter can parse
- Text files: Checks if suffix is `.md`, `.txt`, `.rst`, `.markdown`

### 3. Tree-sitter Parser

**Purpose:** Parses source code files into Abstract Syntax Trees (ASTs).

**Key Functions:**
- `get_parser(file_path)`: Detects language and returns parsed tree
- `support_file(file_path)`: Checks if file type is supported

**Supported Languages:** Python, JavaScript, TypeScript, Java, C, C++, C#, Go, Ruby, Rust, SQL, Kotlin, PHP, HTML, and more.

### 4. Symbol Extractor

**Purpose:** Extracts code symbols (functions, classes, methods) from AST.

**Key Methods:**
- `extract_symbols()`: Walks AST and extracts symbols into `ExtractedSymbol` objects
- `build_symbol_hierarchy()`: Determines parent-child relationships using span containment

**Language-Specific Extractors:**
- `PythonSymbolExtractor`: Extracts classes, functions, methods
- `JavaScriptSymbolExtractor`: Extracts classes, functions, methods, arrow functions
- `TypeScriptSymbolExtractor`: Similar to JavaScript + type definitions

**Extraction Process:**
1. Walk AST tree recursively
2. Find definition nodes (class_definition, function_definition, etc.)
3. Extract: name, signature, docstring, line spans, node types
4. Build qualified names (e.g., "Class.method")
5. Collect AST node types for fingerprinting

### 5. Symbol Hierarchy Building

**Algorithm:** Span-stack algorithm

**Steps:**
1. Sort symbols by (start_line ASC, end_line DESC)
2. Maintain stack of "open" parent symbols
3. For each symbol:
   - Pop stack until finding a parent that contains it (by span)
   - If stack non-empty, top is the parent
   - Push current symbol to stack
4. Create `SymbolHierarchy` relationships
5. Convert to `CONTAINS_SYMBOL` edges

**Why this works:**
- Parents start before children (start_line ASC)
- Parents end after children (end_line DESC for same start)
- Stack tracks currently open scopes
- Span containment determines parent-child relationship

---

## Data Structures

### ExtractedSymbol

Intermediate representation before creating SymbolNode:

```python
@dataclass
class ExtractedSymbol:
    kind: str                    # "function", "class", "method", etc.
    name: str                    # "calculate_sum"
    qualified_name: str | None   # "MathHelper.multiply"
    start_line: int              # 1-indexed
    end_line: int                # 1-indexed
    start_byte: int              # Byte offset
    end_byte: int                # Byte offset
    signature: str               # "def calculate_sum(a: int, b: int) -> int:"
    docstring: str | None        # Docstring text
    node_types: list[str]        # AST node types for fingerprinting
    parent_index: int            # Index of parent in extraction list
    tree_sitter_node: Node       # Reference to AST node (ephemeral)
```

### SymbolNode

Final representation stored in knowledge graph:

```python
@dataclass
class SymbolNode:
    symbol_version_id: str       # Snapshot-scoped ID (per commit)
    stable_symbol_id: str        # Cross-snapshot ID (stable)
    kind: str                    # "function", "class", "method"
    name: str                    # "calculate_sum"
    qualified_name: str | None   # "MathHelper.multiply"
    language: str                # "python"
    relative_path: str           # "src/utils.py"
    start_line: int              # 1-indexed
    end_line: int                # 1-indexed
    signature: str               # Function/class signature
    docstring: str | None        # Docstring
    fingerprint: str | None      # AST fingerprint for matching
```

### FileNode

Represents files and directories:

```python
@dataclass
class FileNode:
    basename: str                # "utils.py"
    relative_path: str           # "src/utils.py"
```

### TextNode

Represents text chunks from documentation:

```python
@dataclass
class TextNode:
    text: str                    # Chunk text content
    start_line: int              # 0-indexed
    end_line: int                # 0-indexed
```

### KnowledgeGraphNode

Wrapper for all node types:

```python
@dataclass
class KnowledgeGraphNode:
    node_id: str                 # Unique ID: "0", "1", "2", ...
    node: FileNode | SymbolNode | TextNode
```

### KnowledgeGraphEdge

Represents relationships:

```python
@dataclass
class KnowledgeGraphEdge:
    source_node: KnowledgeGraphNode
    target_node: KnowledgeGraphNode
    edge_type: KnowledgeGraphEdgeType
```

**Edge Types:**
- `HAS_FILE`: FileNode → FileNode (directory contains file/dir)
- `HAS_SYMBOL`: FileNode → SymbolNode (file contains symbol)
- `HAS_TEXT`: FileNode → TextNode (file contains text chunk)
- `CONTAINS_SYMBOL`: SymbolNode → SymbolNode (class contains method)
- `NEXT_CHUNK`: TextNode → TextNode (sequential text chunks)
- `CALLS`: SymbolNode → SymbolNode (function calls function)
- `IMPORTS`: FileNode → FileNode/SymbolNode (import relationship)

---

## Summary

The repository parsing flow follows these steps:

1. **Entry Point:** `RepoParsingService.parse_repository()` receives repository path
2. **Initialization:** `RepoGraphBuilder` is created with configuration
3. **Root Node:** Create root `FileNode` for repository root
4. **Recursive Traversal:** Walk directory tree, creating `FileNode` hierarchy
5. **File Processing:** For each file:
   - Create `FileNode`
   - Detect file type (code vs. text)
   - Route to appropriate handler
6. **Code Files:** Parse with Tree-sitter → Extract symbols → Create `SymbolNode`s → Build hierarchy
7. **Text Files:** Read content → Split into chunks → Create `TextNode`s → Link chunks
8. **Edge Creation:** Create `HAS_FILE`, `HAS_SYMBOL`, `HAS_TEXT`, `CONTAINS_SYMBOL`, `NEXT_CHUNK` edges
9. **Aggregation:** Collect all nodes and edges into `RepoGraphResult`
10. **Return:** Return complete knowledge graph representation

The result is a comprehensive knowledge graph that captures:
- Directory structure (FileNode hierarchy)
- Code symbols with locations (SymbolNodes)
- Symbol relationships (CONTAINS_SYMBOL)
- Documentation content (TextNodes)
- All relationships (edges)

This graph can then be persisted to Neo4j for querying and analysis.

