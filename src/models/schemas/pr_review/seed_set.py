"""
Seed Set Models

Contains Pydantic schemas for the authoritative PR overlay data (symbols extracted from diff hunks).
The seed set represents the starting point for context assembly and review generation.
"""

from pydantic import BaseModel, Field, validator, computed_field
from typing import List, Optional, Literal, Set
from enum import Enum


class SeedFileReason(str, Enum):
    """Reasons why a file couldn't be mapped to symbols."""
    NO_SYMBOL_MATCH = "no_symbol_match"  # File has changes but no symbols could be extracted
    PATCH_MISSING = "patch_missing"      # No patch data available from GitHub
    FILE_DELETED = "file_deleted"        # File was deleted in PR
    BINARY_FILE = "binary_file"          # File is binary, no AST analysis possible
    PARSE_ERROR = "parse_error"          # AST parsing failed for this file


class SymbolKind(str, Enum):
    """Symbol kinds that can be extracted from code."""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    STRUCT = "struct"
    CONSTANT = "constant"
    VARIABLE = "variable"
    PROPERTY = "property"
    CONSTRUCTOR = "constructor"
    DESTRUCTOR = "destructor"


class SeedSymbol(BaseModel):
    """Symbol extracted from PR diff hunks (authoritative overlay data)."""

    # Location in PR head (authoritative source)
    file_path: str = Field(..., description="Relative file path from repository root")
    start_line: int = Field(..., description="Starting line number in PR head", ge=1)
    end_line: int = Field(..., description="Ending line number in PR head", ge=1)

    # Symbol identification
    kind: SymbolKind = Field(..., description="Symbol type/kind")
    name: str = Field(..., description="Symbol name as found in code")
    qualified_name: Optional[str] = Field(
        None,
        description="Fully qualified name (e.g., 'ClassName.methodName')"
    )

    # Programming language context
    language: str = Field(..., description="Programming language (e.g., 'python', 'javascript')")

    # Symbol content and metadata
    signature: Optional[str] = Field(None, description="Function/method signature if applicable")
    docstring: Optional[str] = Field(None, description="Documentation string if available")

    # PR context and traceability
    hunk_ids: List[str] = Field(
        ...,
        description="List of diff hunk IDs that overlap with this symbol",
        min_items=1
    )

    # Computed fingerprint for symbol matching
    fingerprint: Optional[str] = Field(
        None,
        description="AST-based fingerprint for matching with Neo4j symbols"
    )

    @validator('end_line')
    def validate_line_range(cls, v, values):
        """Ensure end_line >= start_line."""
        if 'start_line' in values and v < values['start_line']:
            raise ValueError('end_line must be >= start_line')
        return v

    @validator('file_path')
    def validate_file_path(cls, v):
        """Normalize and validate file path."""
        if not v.strip():
            raise ValueError('File path cannot be empty')
        return v.strip().replace('\\', '/').strip('/')

    @validator('name')
    def validate_symbol_name(cls, v):
        """Validate symbol name is not empty."""
        if not v.strip():
            raise ValueError('Symbol name cannot be empty')
        return v.strip()

    @validator('hunk_ids')
    def validate_hunk_ids(cls, v):
        """Ensure hunk IDs are unique and not empty."""
        if not v:
            raise ValueError('At least one hunk ID is required')
        cleaned_ids = [hunk_id.strip() for hunk_id in v if hunk_id.strip()]
        if len(cleaned_ids) != len(set(cleaned_ids)):
            raise ValueError('Hunk IDs must be unique')
        return cleaned_ids

    @computed_field
    @property
    def line_span(self) -> int:
        """Number of lines this symbol spans."""
        return self.end_line - self.start_line + 1

    @computed_field
    @property
    def display_name(self) -> str:
        """Display-friendly symbol name."""
        if self.qualified_name:
            return f"{self.qualified_name} ({self.kind})"
        return f"{self.name} ({self.kind})"

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "file_path": "src/utils.py",
                "start_line": 15,
                "end_line": 25,
                "kind": "function",
                "name": "calculate_sum",
                "qualified_name": "calculate_sum",
                "language": "python",
                "signature": "def calculate_sum(a: int, b: int) -> int:",
                "docstring": "Add two numbers together with validation.",
                "hunk_ids": ["hunk_1_src_utils_py"],
                "fingerprint": "func_calculate_sum_int_int_int_abc123"
            }
        }


class SeedFile(BaseModel):
    """File that couldn't be mapped to symbols but has changes."""

    file_path: str = Field(..., description="Relative file path from repository root")
    reason: SeedFileReason = Field(..., description="Reason why symbols couldn't be extracted")
    change_type: str = Field(..., description="Type of change: added, modified, removed, renamed")

    # Additional context
    error_message: Optional[str] = Field(None, description="Error details if applicable")
    language: Optional[str] = Field(None, description="Detected language if available")
    line_count: Optional[int] = Field(None, description="Number of lines changed", ge=0)

    @validator('file_path')
    def validate_file_path(cls, v):
        """Normalize and validate file path."""
        if not v.strip():
            raise ValueError('File path cannot be empty')
        return v.strip().replace('\\', '/').strip('/')

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "file_path": "README.md",
                "reason": "no_symbol_match",
                "change_type": "modified",
                "language": "markdown",
                "line_count": 5
            }
        }


class SeedSetS0(BaseModel):
    """Complete seed set from PR analysis (authoritative overlay data)."""

    seed_symbols: List[SeedSymbol] = Field(
        default_factory=list,
        description="Symbols extracted from diff hunks"
    )
    seed_files: List[SeedFile] = Field(
        default_factory=list,
        description="Files with changes but no extractable symbols"
    )

    # Generation metadata
    extraction_timestamp: Optional[str] = Field(None, description="When the seed set was created")
    ast_parser_version: Optional[str] = Field(None, description="Version of AST parser used")

    @validator('seed_symbols')
    def validate_unique_symbols(cls, v):
        """Ensure no duplicate symbols (same file + name + line range)."""
        seen = set()
        for symbol in v:
            key = (symbol.file_path, symbol.name, symbol.start_line, symbol.end_line)
            if key in seen:
                raise ValueError(f'Duplicate symbol found: {symbol.name} at {symbol.file_path}:{symbol.start_line}-{symbol.end_line}')
            seen.add(key)
        return v

    @validator('seed_files')
    def validate_unique_files(cls, v):
        """Ensure no duplicate file paths in seed files."""
        file_paths = [f.file_path for f in v]
        if len(file_paths) != len(set(file_paths)):
            raise ValueError('Duplicate file paths found in seed files')
        return v

    @computed_field
    @property
    def total_symbols(self) -> int:
        """Total number of symbols in the seed set."""
        return len(self.seed_symbols)

    @computed_field
    @property
    def total_files(self) -> int:
        """Total number of unique files represented (symbols + unmapped files)."""
        symbol_files = {s.file_path for s in self.seed_symbols}
        seed_files = {f.file_path for f in self.seed_files}
        return len(symbol_files | seed_files)

    @computed_field
    @property
    def languages(self) -> List[str]:
        """List of programming languages found in the seed set."""
        languages = set()
        for symbol in self.seed_symbols:
            languages.add(symbol.language)
        for file in self.seed_files:
            if file.language:
                languages.add(file.language)
        return sorted(list(languages))

    @computed_field
    @property
    def symbol_kinds(self) -> List[str]:
        """List of symbol kinds found in the seed set."""
        kinds = {s.kind for s in self.seed_symbols}
        return sorted(list(kinds))

    def get_symbols_by_file(self, file_path: str) -> List[SeedSymbol]:
        """Get all symbols for a specific file."""
        return [s for s in self.seed_symbols if s.file_path == file_path]

    def get_symbols_by_kind(self, kind: SymbolKind) -> List[SeedSymbol]:
        """Get all symbols of a specific kind."""
        return [s for s in self.seed_symbols if s.kind == kind]

    def has_symbols_for_file(self, file_path: str) -> bool:
        """Check if file has extractable symbols."""
        return any(s.file_path == file_path for s in self.seed_symbols)

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "seed_symbols": [
                    {
                        "file_path": "src/utils.py",
                        "start_line": 15,
                        "end_line": 25,
                        "kind": "function",
                        "name": "calculate_sum",
                        "language": "python",
                        "hunk_ids": ["hunk_1_src_utils_py"]
                    }
                ],
                "seed_files": [
                    {
                        "file_path": "README.md",
                        "reason": "no_symbol_match",
                        "change_type": "modified"
                    }
                ],
                "extraction_timestamp": "2026-01-15T10:30:00Z"
            }
        }