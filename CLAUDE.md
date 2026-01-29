# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Sentinel is an AI-powered code review system that analyzes pull requests, detects bugs, and provides intelligent feedback using Temporal workflows and LangGraph for multi-step reasoning.

## Development Commands

```bash
# Install dependencies
make install           # or: poetry install

# Activate virtual environment
poetry shell

# Run application
python -m src.main                    # Direct execution
uvicorn src.main:app --reload         # With auto-reload

# Run tests
pytest                                # All tests
pytest -m unit                        # Unit tests only
pytest -m integration                 # Integration tests only
pytest tests/path/to/test.py -v       # Specific test file
pytest --cov=src --cov-report=html    # With coverage

# Code quality
black src tests                       # Format code
isort src tests                       # Sort imports
mypy src                              # Type checking

# Docker
docker compose up --build             # Start all services
docker compose down                   # Stop services
docker compose down -v                # Stop and remove volumes
```

### Key Services (Docker Compose)

| Service | Port | Purpose |
|---------|------|---------|
| FastAPI App | 8000 | REST API & Webhooks |
| PostgreSQL | 5432 | Metadata persistence |
| Neo4j | 7687 (Bolt), 7474 (HTTP) | Knowledge Graph |
| ngrok | 4040 | Public webhook tunnel |

## Key Documentation

### Architecture & Design

| Topic | Documentation |
|-------|---------------|
| System architecture | `plans/architecture.md` |
| Implementation phases | `plans/implementation-phases.md` |
| Tech stack | `plans/tech-stack.md` |
| API contracts | `plans/api_contracts.md` |
| Database schema | `plans/db_schema.md` |
| Technical requirements | `plans/TRD.md` |

### Module Documentation

| Module | Documentation |
|--------|---------------|
| Temporal activities | `src/activities/README.md` |
| Temporal workflows | `src/workflows/README.md` |
| Worker processes | `src/workers/README.md` |
| Context assembly | `src/langgraph/context_assembly/README.md` |
| GitHub service | `src/services/github/README.md` |
| Knowledge graph | `src/services/kg/README.md` |
| LLM service | `src/services/llm/README.md` |
| Parser/Extractor | `src/parser/README.md` |

## Project Structure

```
AI-Code-Reviewer-Backend/
├── src/
│   ├── main.py                    # FastAPI app entry point
│   ├── activities/                # Temporal activities
│   ├── workflows/                 # Temporal workflows
│   ├── workers/                   # Temporal workers
│   ├── langgraph/                 # LangGraph nodes
│   │   ├── context_assembly/      # Context building pipeline
│   │   └── review_generation/     # Review generation pipeline
│   ├── api/fastapi/               # REST API routes
│   ├── services/                  # Business logic layer
│   ├── models/                    # Data models
│   │   ├── db/                    # SQLAlchemy ORM models
│   │   ├── graph/                 # Neo4j graph models
│   │   └── schemas/               # Pydantic validation schemas
│   ├── core/                      # Configuration & connections
│   ├── parser/                    # Code parsing (Tree-sitter)
│   ├── utils/                     # Utilities & logging
│   └── exceptions/                # Custom exceptions
├── tests/                         # Test suite (mirrors src/)
├── plans/                         # Architecture & design docs
├── docker-compose.yaml            # Local dev environment
└── pyproject.toml                 # Poetry dependencies
```

## Critical Pre-Implementation Checks

Before writing code, review these critical patterns that will block PRs if violated:

### Temporal Activities
- **No FastAPI dependencies**: Services must create their own DB sessions, not use `Depends(get_db)`
- **Dict-based I/O**: Activities receive and return dicts for deterministic serialization
- **Error classification**: Use `ApplicationError(non_retryable=True)` for permanent failures (401, 403, 404)
- **Heartbeats**: Send heartbeats for long-running operations
- See: `src/activities/README.md`

### Workflow Determinism
- **No randomness**: Avoid `random`, `uuid4()`, `datetime.now()` in workflows
- **No I/O**: All external operations must go through activities
- **Guaranteed cleanup**: Always use try-finally for resource cleanup
- See: `src/workflows/README.md`

### LangGraph Nodes
- **Inherit from BaseNode**: All nodes extend `BaseNode` class
- **State mutation**: Update state dict and return modified state
- **Hard limits**: Respect context pack limits (35 items, 120K chars)
- See: `src/langgraph/context_assembly/README.md`

### Pydantic Schemas
- **Serialization round-trips**: Handle enum values after `model_dump()` + reconstruction
- **Use `change_type_str` property**: For safe enum access after deserialization
- **Pre-validators**: Normalize types during construction
- See: `src/models/schemas/pr_review/pr_patch.py`

## Quick Checks Before Implementing

### Service Layer

| Need | Solution | Reference |
|------|----------|-----------|
| GitHub API calls | Use `PRApiClient` with retry logic | `src/services/github/` |
| Neo4j queries | Use `KGQueryService` | `src/services/kg/` |
| LLM calls | Use `ClaudeClient` or `GeminiClient` | `src/services/llm/` |
| Repository cloning | Use `RepoCloneService` | `src/services/cloning/` |
| Diff parsing | Use `UnifiedDiffParser` | `src/services/diff_parsing/` |
| Symbol extraction | Use `SeedSetBuilder` | `src/services/seed_generation/` |
| Database persistence | Use service classes, not raw sessions | `src/services/persist_metadata/` |

### Common Patterns

| Pattern | Implementation | Reference |
|---------|---------------|-----------|
| Activity definition | `@activity.defn` decorator | `src/activities/` |
| Workflow definition | `@workflow.defn` decorator | `src/workflows/` |
| LangGraph node | Inherit `BaseNode`, implement `invoke()` | `src/langgraph/` |
| Error handling | Classify retryable vs non-retryable | `src/exceptions/` |
| Logging | Use `get_logger(__name__)` | `src/utils/logging/` |
| Validation | Use Pydantic schemas at boundaries | `src/models/schemas/` |

### Hard Limits (Context Assembly)

| Limit | Value | Description |
|-------|-------|-------------|
| Max context items | 35 | Maximum items in context pack |
| Max total characters | 120,000 | Total char limit for LLM |
| Max lines per snippet | 120 | Max lines per code snippet |
| Max relationship hops | 1 | Neo4j expansion depth |
| Context timeout | 300s | Max context assembly time |
| Review timeout | 600s | Max review generation time |

## Environment Variables

```bash
# GitHub Integration
GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET
GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_OAUTH_CLIENT_ID
GITHUB_OAUTH_CLIENT_SECRET, GITHUB_REDIRECT_URI

# Databases
DATABASE_URL                          # PostgreSQL with pgVector
NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE

# Temporal
TEMPORAL_SERVER_URL

# LLM
LLM_PROVIDER                          # "gemini" or "claude"
ANTHROPIC_API_KEY, GEMINI_API_KEY

# Services
SUPABASE_URL, SUPABASE_KEY
NGROK_AUTHTOKEN
```

## Testing

### Test Organization
- Tests mirror `src/` directory structure
- Use `@pytest.mark.unit` and `@pytest.mark.integration` markers
- Async tests require `@pytest.mark.asyncio` decorator

### Test Patterns
```python
# Activity test
@pytest.mark.asyncio
async def test_activity_name():
    result = await activity_name(input_data)
    assert "expected_key" in result

# Service test with mocking
@pytest.mark.asyncio
async def test_service_method():
    with patch('src.services.module.Dependency') as mock:
        service = ServiceClass()
        result = await service.method()
        assert result.status == "success"
```

## PR Review Pipeline Flow

```
GitHub Webhook → fetch_pr_context → clone_pr_head → build_seed_set
    → retrieve_kg_candidates → [LangGraph] Context Assembly
    → [LangGraph] Review Generation → anchor_and_publish → cleanup
```

### Key Activities
1. `fetch_pr_context_activity` - GitHub API data fetching
2. `clone_pr_head_activity` - Clone PR head commit
3. `build_seed_set_activity` - AST-based symbol extraction
4. `retrieve_kg_candidates_activity` - Query knowledge graph
5. `retrieve_and_assemble_context_activity` - Context assembly via LangGraph
6. `generate_review_activity` - AI review generation via LangGraph
7. `anchor_and_publish_activity` - Publish to GitHub with inline comments
8. `cleanup_pr_clone_activity` - Resource cleanup

## Data Authority

- **PR-head clone**: Authoritative for code spans, line numbers, actual content
- **Neo4j KG**: Authoritative for symbol relationships (CALLS, IMPORTS, CONTAINS)
- **PostgreSQL**: Metadata persistence, audit trails, workflow tracking

## General Instruction
"For every project, write a detailed FOR[omkargade].md file that explains the whole project in plain language. 

Explain the technical architecture, the structure of the codebase and how the various parts are connected, the technologies used, why we made these technical decisions, and lessons I can learn from it (this should include the bugs we ran into and how we fixed them, potential pitfalls and how to avoid them in the future, new technologies used, how good engineers think and work, best practices, etc). 

It should be very engaging to read; don't make it sound like boring technical documentation/textbook. Where appropriate, use analogies and anecdotes to make it more understandable and memorable."

# Bash Guidelines

## IMPORTANT: Avoid commands that cause output buffering issues
- DO NOT pipe output through `head`, `tail`, `less`, or `more` when monitoring or checking command output
- DO NOT use `| head -n X` or `| tail -n X` to truncate output - these cause buffering problems
- Instead, let commands complete fully, or use `--max-lines` flags if the command supports them
- For log monitoring, prefer reading files directly rather than piping through filters

## When checking command output:
- Run commands directly without pipes when possible
- If you need to limit output, use command-specific flags (e.g., `git log -n 10` instead of `git log | head -10`)
- Avoid chained pipes that can cause output to buffer indefinitely