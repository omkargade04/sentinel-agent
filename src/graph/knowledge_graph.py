"""Build an in-memory knowledge graph representation of a codebase.

In the knowledge graph, we have the following node types:
* FileNode: Represents a file or directory.
* SymbolNode: Represents a code symbol (function/class/method/interface/struct/etc.).
* TextNode: Represents a chunk of file text (code or documentation).

and the following edge types:
* HAS_FILE: Relationship between two FileNode instances when one directory contains the other file/dir.
* HAS_SYMBOL: Relationship between FileNode and SymbolNode when the file defines the symbol.
* HAS_TEXT: Relationship between FileNode and TextNode when the text chunk belongs to the file.
* NEXT_CHUNK: Relationship between two TextNode instances when one is the next chunk of the same file.
* CONTAINS_SYMBOL: Relationship between two SymbolNode instances for nesting (e.g., class -> method).
* CALLS: Relationship between two SymbolNode instances for best-effort call graph edges (may include confidence).
* IMPORTS: Relationship from FileNode to FileNode/SymbolNode for best-effort import/use edges (may include confidence).

In this way, we have all the directory structure, source code, and text information in a single knowledge graph.
This knowledge graph can be persisted to Neo4j and queried by retrieval agents (e.g., LangGraph) to assemble
compact, relevant context packs for PR review and interactive questions.
"""