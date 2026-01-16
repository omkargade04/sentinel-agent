"""
PR Review Configuration Framework

Centralized configuration management for the PR review pipeline with hard limits,
environment-based settings, and validation rules.
"""

import os
from typing import Dict, Optional, List
from pydantic import Field, validator, BaseModel
from pydantic_settings import BaseSettings
from enum import Enum


class LogLevel(str, Enum):
    """Logging levels for PR review pipeline."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"


class PRReviewLimits(BaseModel):
    """Hard limits configuration for PR review processing."""

    # File processing limits
    max_changed_files: int = Field(
        default=50,
        description="Maximum number of changed files to process",
        ge=1,
        le=200
    )
    max_hunks_per_file: int = Field(
        default=30,
        description="Maximum number of hunks per file",
        ge=1,
        le=100
    )
    max_seed_symbols: int = Field(
        default=30,
        description="Maximum number of seed symbols to extract",
        ge=1,
        le=100
    )

    # Context assembly limits (critical for LLM token constraints)
    max_context_items: int = Field(
        default=35,
        description="Maximum number of context items",
        ge=5,
        le=50
    )
    max_total_characters: int = Field(
        default=120_000,
        description="Maximum total character count (~30k tokens)",
        ge=10_000,
        le=500_000
    )
    max_lines_per_snippet: int = Field(
        default=120,
        description="Maximum lines per code snippet",
        ge=10,
        le=500
    )
    max_chars_per_item: int = Field(
        default=2000,
        description="Maximum characters per context item",
        ge=100,
        le=10_000
    )

    # Neo4j query limits
    max_hops: int = Field(
        default=1,
        description="Maximum relationship traversal hops",
        ge=0,
        le=3
    )
    max_callers_per_seed: int = Field(
        default=8,
        description="Maximum callers to include per seed symbol",
        ge=1,
        le=20
    )
    max_callees_per_seed: int = Field(
        default=8,
        description="Maximum callees to include per seed symbol",
        ge=1,
        le=20
    )

    # Clone resource limits
    max_clone_size_mb: int = Field(
        default=1000,
        description="Maximum clone size in MB",
        ge=10,
        le=5000
    )
    max_clone_files: int = Field(
        default=50000,
        description="Maximum number of files in clone",
        ge=100,
        le=200000
    )

    # Diff parsing limits
    max_hunk_size_lines: int = Field(
        default=1000,
        description="Maximum lines per hunk to process",
        ge=10,
        le=10000
    )
    max_file_size_kb: int = Field(
        default=1024,
        description="Maximum file size in KB to process diffs",
        ge=1,
        le=10240
    )
    skip_binary_files: bool = Field(
        default=True,
        description="Whether to skip binary files during processing"
    )

    # Review output limits
    max_findings_per_review: int = Field(
        default=20,
        description="Maximum findings per review",
        ge=1,
        le=50
    )
    min_finding_confidence: float = Field(
        default=0.5,
        description="Minimum confidence threshold for findings",
        ge=0.0,
        le=1.0
    )
    
        # KG candidate retrieval limits
    max_kg_symbol_matches_per_seed: int = Field(
        default=5,
        description="Maximum KG symbol matches to retrieve per seed symbol",
        ge=1,
        le=20
    )
    max_contains_per_seed: int = Field(
        default=5,
        description="Maximum CONTAINS_SYMBOL neighbors per matched symbol",
        ge=1,
        le=20
    )
    max_import_files_per_seed_file: int = Field(
        default=10,
        description="Maximum import neighbors (files) to retrieve per seed file",
        ge=1,
        le=30
    )
    max_kg_docs_total: int = Field(
        default=20,
        description="Maximum documentation text nodes to retrieve from KG",
        ge=1,
        le=50
    )
    max_seeds_to_process: int = Field(
        default=100,
        description="Maximum seed symbols to process for KG queries (prevents runaway)",
        ge=10,
        le=500
    )
    max_total_kg_candidates: int = Field(
        default=500,
        description="Hard ceiling on total KG candidates returned",
        ge=50,
        le=2000
    )
    
    max_symbols_per_file: int = 200
    max_file_size_bytes: int = 1_000_000  # 1MB
    supported_languages: list[str] = ["python", "javascript", "typescript"]

    class Config:
        schema_extra = {
            "example": {
                "max_changed_files": 50,
                "max_context_items": 35,
                "max_total_characters": 120000,
                "max_findings_per_review": 20,
                "max_kg_symbol_matches_per_seed": 5,
                "max_total_kg_candidates": 500
            }
        }


class PRReviewTimeouts(BaseModel):
    """Timeout configuration for different pipeline stages."""

    # Activity timeouts (in seconds)
    fetch_pr_context_timeout: int = Field(
        default=120,
        description="GitHub API operations timeout",
        ge=30,
        le=600
    )
    clone_pr_head_timeout: int = Field(
        default=300,
        description="Repository cloning timeout",
        ge=60,
        le=900
    )
    build_seed_set_timeout: int = Field(
        default=180,
        description="AST analysis timeout",
        ge=60,
        le=600
    )
    context_assembly_timeout: int = Field(
        default=300,
        description="Context assembly timeout",
        ge=120,
        le=900
    )
    review_generation_timeout: int = Field(
        default=600,
        description="Review generation timeout",
        ge=300,
        le=1800
    )
    publish_review_timeout: int = Field(
        default=120,
        description="Review publishing timeout",
        ge=30,
        le=300
    )

    # Phase 2 specific timeouts
    github_api_timeout: int = Field(
        default=30,
        description="Individual GitHub API request timeout",
        ge=5,
        le=120
    )
    diff_parsing_timeout: int = Field(
        default=60,
        description="Diff parsing operation timeout",
        ge=10,
        le=300
    )
    clone_integrity_check_timeout: int = Field(
        default=30,
        description="Clone SHA validation timeout",
        ge=5,
        le=120
    )

    # Retry configuration
    max_retry_attempts: int = Field(
        default=3,
        description="Maximum retry attempts for failed operations",
        ge=1,
        le=5
    )
    retry_backoff_factor: float = Field(
        default=2.0,
        description="Exponential backoff factor for retries",
        ge=1.0,
        le=5.0
    )

    class Config:
        schema_extra = {
            "example": {
                "context_assembly_timeout": 300,
                "review_generation_timeout": 600,
                "max_retry_attempts": 3
            }
        }


class GitHubAPIConfig(BaseModel):
    """GitHub API configuration and rate limiting."""

    # Rate limiting
    requests_per_hour: int = Field(
        default=5000,
        description="GitHub API requests per hour limit",
        ge=100,
        le=15000
    )
    concurrent_requests: int = Field(
        default=10,
        description="Maximum concurrent GitHub API requests",
        ge=1,
        le=50
    )

    # Request configuration
    request_timeout: int = Field(
        default=30,
        description="Individual request timeout in seconds",
        ge=5,
        le=120
    )
    retry_attempts: int = Field(
        default=3,
        description="Retry attempts for failed requests",
        ge=1,
        le=5
    )
    retry_backoff: float = Field(
        default=2.0,
        description="Backoff factor for retries",
        ge=1.0,
        le=5.0
    )

    # API endpoint configuration
    api_base_url: str = Field(
        default="https://api.github.com",
        description="GitHub API base URL"
    )
    api_version: str = Field(
        default="2022-11-28",
        description="GitHub API version header"
    )
    user_agent: str = Field(
        default="AI-Code-Reviewer/1.0",
        description="User agent for API requests"
    )

    # PR-specific API limits
    max_pr_files_per_request: int = Field(
        default=300,
        description="Maximum files to fetch per GitHub API request",
        ge=1,
        le=300
    )
    max_pr_file_pages: int = Field(
        default=100,
        description="Maximum pages of files to fetch for a PR",
        ge=1,
        le=1000
    )

    # Publishing configuration
    max_inline_comments: int = Field(
        default=30,
        description="Maximum inline comments per review",
        ge=1,
        le=100
    )
    review_body_max_length: int = Field(
        default=65536,
        description="Maximum characters in review body",
        ge=1000,
        le=100_000
    )

    class Config:
        schema_extra = {
            "example": {
                "requests_per_hour": 5000,
                "max_inline_comments": 30,
                "retry_attempts": 3
            }
        }


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: LLMProvider = Field(
        default=LLMProvider.OPENAI,
        description="LLM provider to use"
    )
    model: str = Field(
        default="gpt-4",
        description="Model name/identifier"
    )
    temperature: float = Field(
        default=0.1,
        description="Temperature for LLM responses",
        ge=0.0,
        le=2.0
    )
    max_tokens: Optional[int] = Field(
        default=4000,
        description="Maximum tokens for completion",
        ge=100,
        le=100_000
    )

    # Request configuration
    timeout: int = Field(
        default=60,
        description="LLM request timeout in seconds",
        ge=10,
        le=300
    )
    retry_attempts: int = Field(
        default=3,
        description="Retry attempts for failed LLM requests",
        ge=1,
        le=5
    )

    class Config:
        use_enum_values = True
        schema_extra = {
            "example": {
                "provider": "openai",
                "model": "gpt-4",
                "temperature": 0.1,
                "max_tokens": 4000
            }
        }


class PRReviewSettings(BaseSettings):
    """Main configuration settings for PR review pipeline."""

    # ============================================================================
    # CORE CONFIGURATION
    # ============================================================================

    # Environment
    environment: str = Field(
        default="development",
        description="Deployment environment"
    )
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level"
    )
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )

    # ============================================================================
    # DATABASE CONFIGURATION
    # ============================================================================

    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/postgres",
        description="PostgreSQL database URL"
    )

    # ============================================================================
    # NEO4J CONFIGURATION
    # ============================================================================

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j database URI"
    )
    neo4j_username: str = Field(
        default="neo4j",
        description="Neo4j username"
    )
    neo4j_password: str = Field(
        default="password",
        description="Neo4j password"
    )
    neo4j_database: str = Field(
        default="neo4j",
        description="Neo4j database name"
    )

    # ============================================================================
    # GITHUB CONFIGURATION
    # ============================================================================

    github_app_id: int = Field(
        default=0,
        description="GitHub App ID",
        gt=0
    )
    github_private_key: str = Field(
        default="",
        description="GitHub App private key (PEM format)"
    )
    github_webhook_secret: str = Field(
        default="",
        description="GitHub webhook secret"
    )

    # ============================================================================
    # TEMPORAL CONFIGURATION
    # ============================================================================

    temporal_host: str = Field(
        default="localhost:7233",
        description="Temporal server host"
    )
    temporal_namespace: str = Field(
        default="default",
        description="Temporal namespace"
    )
    temporal_task_queue: str = Field(
        default="pr-review-pipeline",
        description="Temporal task queue name"
    )

    # ============================================================================
    # LLM CONFIGURATION
    # ============================================================================

    # OpenAI
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key"
    )
    openai_organization: Optional[str] = Field(
        default=None,
        description="OpenAI organization ID"
    )

    # Azure OpenAI
    azure_openai_endpoint: Optional[str] = Field(
        default=None,
        description="Azure OpenAI endpoint"
    )
    azure_openai_api_key: Optional[str] = Field(
        default=None,
        description="Azure OpenAI API key"
    )
    azure_openai_deployment: Optional[str] = Field(
        default=None,
        description="Azure OpenAI deployment name"
    )

    # Anthropic
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API key"
    )

    # ============================================================================
    # PIPELINE LIMITS AND CONFIGURATION
    # ============================================================================

    limits: PRReviewLimits = Field(
        default_factory=PRReviewLimits,
        description="Hard limits for processing"
    )
    timeouts: PRReviewTimeouts = Field(
        default_factory=PRReviewTimeouts,
        description="Timeout configuration"
    )
    github_api: GitHubAPIConfig = Field(
        default_factory=GitHubAPIConfig,
        description="GitHub API configuration"
    )
    llm: LLMConfig = Field(
        default_factory=LLMConfig,
        description="LLM configuration"
    )

    # ============================================================================
    # FEATURE FLAGS
    # ============================================================================

    enable_context_caching: bool = Field(
        default=True,
        description="Enable context assembly caching"
    )
    enable_kg_fallback: bool = Field(
        default=True,
        description="Enable knowledge graph fallback strategies"
    )
    enable_dry_run_mode: bool = Field(
        default=False,
        description="Enable dry run mode (no GitHub publishing)"
    )
    enable_metrics_collection: bool = Field(
        default=True,
        description="Enable metrics and telemetry collection"
    )

    # ============================================================================
    # VALIDATION
    # ============================================================================

    @validator('github_app_id')
    def validate_github_app_id(cls, v, values):
        """Validate GitHub App ID is provided in production."""
        # Allow 0 in development/testing, but require positive in production
        if v == 0 and values.get('environment') == 'production':
            raise ValueError('GitHub App ID must be positive in production')
        if v < 0:
            raise ValueError('GitHub App ID cannot be negative')
        return v

    @validator('github_private_key')
    def validate_github_private_key(cls, v, values):
        """Validate GitHub private key format."""
        if not v and values.get('environment') == 'production':
            raise ValueError('GitHub private key required in production')
        if v and not v.startswith('-----BEGIN'):
            raise ValueError('GitHub private key must be in PEM format')
        return v

    @validator('openai_api_key')
    def validate_openai_api_key(cls, v, values):
        """Validate OpenAI API key is provided when using OpenAI."""
        if values.get('llm', {}).get('provider') == LLMProvider.OPENAI and not v:
            raise ValueError('OpenAI API key required when using OpenAI provider')
        return v

    @validator('database_url')
    def validate_database_url(cls, v):
        """Validate database URL format."""
        if not v.startswith(('postgresql://', 'postgres://')):
            raise ValueError('Database URL must be a PostgreSQL connection string')
        return v

    @validator('neo4j_uri')
    def validate_neo4j_uri(cls, v):
        """Validate Neo4j URI format."""
        if not v.startswith(('bolt://', 'neo4j://', 'bolt+s://', 'neo4j+s://')):
            raise ValueError('Neo4j URI must use bolt:// or neo4j:// protocol')
        return v

    # ============================================================================
    # HELPER METHODS FOR PHASE 2
    # ============================================================================

    def get_github_api_config(self) -> Dict[str, Any]:
        """Get GitHub API configuration for PR operations."""
        return {
            "base_url": self.github_api.api_base_url,
            "api_version": self.github_api.api_version,
            "user_agent": self.github_api.user_agent,
            "timeout": self.timeouts.github_api_timeout,
            "retry_attempts": self.github_api.retry_attempts,
            "retry_backoff": self.github_api.retry_backoff,
            "rate_limit": {
                "requests_per_hour": self.github_api.requests_per_hour,
                "concurrent_requests": self.github_api.concurrent_requests,
            }
        }

    def get_clone_config(self) -> Dict[str, Any]:
        """Get clone operation configuration."""
        return {
            "max_size_mb": self.limits.max_clone_size_mb,
            "max_files": self.limits.max_clone_files,
            "timeout": self.timeouts.clone_pr_head_timeout,
            "integrity_check_timeout": self.timeouts.clone_integrity_check_timeout,
        }

    def get_diff_parsing_config(self) -> Dict[str, Any]:
        """Get diff parsing configuration."""
        return {
            "max_changed_files": self.limits.max_changed_files,
            "max_hunks_per_file": self.limits.max_hunks_per_file,
            "max_hunk_size_lines": self.limits.max_hunk_size_lines,
            "max_file_size_kb": self.limits.max_file_size_kb,
            "skip_binary_files": self.limits.skip_binary_files,
            "timeout": self.timeouts.diff_parsing_timeout,
        }

    def should_skip_large_pr(self, files_changed: int, total_changes: int) -> bool:
        """Determine if PR should be skipped due to size."""
        return (
            files_changed > self.limits.max_changed_files or
            total_changes > self.limits.max_changed_files * 50  # Average 50 changes per file
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        # Map environment variables to nested config
        env_nested_delimiter = "__"


# ============================================================================
# CONFIGURATION FACTORY
# ============================================================================

def get_pr_review_settings() -> PRReviewSettings:
    """
    Get PR review settings with environment-based overrides.

    Environment variables can override any setting using double underscore notation:
    - PR_REVIEW_LIMITS__MAX_CONTEXT_ITEMS=50
    - PR_REVIEW_LLM__MODEL=gpt-4-turbo
    - PR_REVIEW_GITHUB_API__RETRY_ATTEMPTS=5
    """
    return PRReviewSettings(_env_prefix="PR_REVIEW_")


def create_development_config() -> PRReviewSettings:
    """Create development-friendly configuration."""
    config = PRReviewSettings(
        environment="development",
        log_level=LogLevel.DEBUG,
        debug=True,
        enable_dry_run_mode=True,  # Safe for development
        limits=PRReviewLimits(
            max_context_items=20,     # Smaller for faster testing
            max_total_characters=50_000,
            max_findings_per_review=10
        ),
        timeouts=PRReviewTimeouts(
            context_assembly_timeout=120,  # Shorter timeouts
            review_generation_timeout=300
        )
    )
    return config


def create_production_config() -> PRReviewSettings:
    """Create production-optimized configuration."""
    config = PRReviewSettings(
        environment="production",
        log_level=LogLevel.INFO,
        debug=False,
        enable_dry_run_mode=False,
        limits=PRReviewLimits(
            max_context_items=35,      # Full limits
            max_total_characters=120_000,
            max_findings_per_review=20
        ),
        timeouts=PRReviewTimeouts(
            context_assembly_timeout=300,  # Full timeouts
            review_generation_timeout=600
        ),
        github_api=GitHubAPIConfig(
            requests_per_hour=4000,    # Conservative rate limiting
            concurrent_requests=5
        )
    )
    return config


# ============================================================================
# GLOBAL SETTINGS INSTANCE
# ============================================================================

# Initialize global settings - can be overridden by tests
pr_review_settings = get_pr_review_settings()