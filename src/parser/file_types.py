from pathlib import Path
import enum

class FileTypes(enum.StrEnum):
    """Enum of all tree-sitter file types"""
    
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    JAVA = "java"
    C = "c"
    CPP = "cpp"
    CSHARP = "csharp"
    GO = "go"
    RUBY = "ruby"
    RUST = "rust"
    SQL = "sql"
    KOTLIN = "kotlin"
    PHP = "php"
    HTML = "html"
    PROPERTIES = "properties"
    YAML = "yaml"
    XML = "xml"
    BASH = "bash"
    UNKNOWN = "UNKNOWN"
    DOCKERFILE = "dockerfile"
    
    @classmethod
    def from_path(cls, path: Path):
        if path.name.lower() == "dockerfile":
            return cls.DOCKERFILE
        
        match path.suffix:
            case ".sh" | ".bash":
                return cls.BASH
            case ".py":
                return cls.PYTHON
            case ".js":
                return cls.JAVASCRIPT
            case ".ts":
                return cls.TYPESCRIPT
            case ".java":
                return cls.JAVA
            case ".c":
                return cls.C
            case ".cpp":
                return cls.CPP
            case ".cs":
                return cls.CSHARP
            case ".go":
                return cls.GO
            case ".rb":
                return cls.RUBY
            case ".rs":
                return cls.RUST
            case ".sql":
                return cls.SQL
            case ".kt":
                return cls.KOTLIN
            case ".php":
                return cls.PHP
            case ".html":
                return cls.HTML
            case ".properties":
                return cls.PROPERTIES
            case ".yaml" | ".yml":
                return cls.YAML
            case ".xml":
                return cls.XML
            case _:
                return cls.UNKNOWN