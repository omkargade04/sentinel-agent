# AI Agent Guide

This guide helps AI agents (Claude Code, Cursor, Copilot, etc.) navigate the Sentinel codebase and documentation effectively.

## Quick Start

Read these docs first based on your task:

| Task | Start Here |
|------|------------|
| Building Temporal activities | `src/activities/README.md` |
| Creating workflows | `src/workflows/README.md` |
| Working with LangGraph nodes | `src/langgraph/context_assembly/README.md` |
| Understanding architecture | `plans/architecture.md` |
| Writing tests | `tests/` + existing test files as examples |
| Adding API routes | `src/api/fastapi/routes/README.md` |
| Working with Knowledge Graph | `src/services/kg/README.md` |
| LLM integration | `src/services/llm/README.md` |

## Documentation Structure

### Architecture & Design (`plans/`)

For understanding system design and making architectural decisions.

| File | Purpose |
|------|---------|
| `architecture.md` | Complete technical architecture, data flow, component responsibilities |
| `implementation-phases.md` | Phased implementation roadmap |
| `tech-stack.md` | Technology stack details and rationale |
| `api_contracts.md` | API contract specifications |
| `db_schema.md` | Database schema design (PostgreSQL + Neo4j) |
| `TRD.md` | Technical Requirements Document |
| `pr_review_v0_pipeline_analysis.md` | PR review pipeline deep dive |
| `kg-query-optimization-plan.md` | Knowledge Graph query optimization |

### Module Documentation (`src/*/README.md`)

For implementing features within specific modules.

#### Core Pipeline

| File | Purpose |
|------|---------|
| `src/activities/README.md` | Temporal activity patterns, error handling, serialization |
| `src/workflows/README.md` | Workflow orchestration, determinism rules, cleanup patterns |
| `src/workers/README.md` | Worker process configuration, task queues |

#### LangGraph Components

| File | Purpose |
|------|---------|
| `src/langgraph/context_assembly/README.md` | Context assembly pipeline, hard limits, ranking |

#### Service Layer

| File | Purpose |
|------|---------|
| `src/services/github/README.md` | GitHub API integration, rate limiting, diff position |
| `src/services/kg/README.md` | Knowledge Graph queries, Neo4j patterns |
| `src/services/llm/README.md` | LLM client abstraction, cost tracking |
| `src/services/indexing/README.md` | Repository indexing service |
| `src/services/repository/README.md` | Repository management |

#### Parser & AST

| File | Purpose |
|------|---------|
| `src/parser/README.md` | Code parsing overview |
| `src/parser/extractor/README.md` | Tree-sitter symbol extraction |

#### API Layer

| File | Purpose |
|------|---------|
| `src/api/fastapi/routes/README.md` | REST API endpoint documentation |

## Common Workflows

### Adding a New Temporal Activity

1. Read `src/activities/README.md` for patterns
2. Check existing activities in `src/activities/pr_review_activities.py`
3. Create activity with `@activity.defn` decorator
4. Handle errors: classify retryable vs non-retryable
5. Use dict-based I/O for serialization
6. Add tests in `tests/activities/`

```python
# Pattern
@activity.defn
async def new_activity(input_data: dict) -> dict:
    service = SomeService()
    try:
        result = await service.do_work(...)
        return {"status": "success", "data": result}
    except Exception as e:
        if is_non_retryable(e):
            raise ApplicationError(str(e), non_retryable=True)
        raise
```

### Adding a LangGraph Node

1. Read `src/langgraph/context_assembly/README.md`
2. Check existing nodes (e.g., `seed_analyzer.py`, `context_ranker.py`)
3. Inherit from `BaseNode`
4. Implement `async def invoke(self, state: dict) -> dict`
5. Respect hard limits (35 items, 120K chars)

```python
# Pattern
class NewNode(BaseNode):
    async def invoke(self, state: ContextAssemblyState) -> dict:
        # Process state
        result = await self.process(state)
        # Update and return state
        return {**state, "new_field": result}
```

### Adding a New Service

1. Check existing services in `src/services/` for patterns
2. Services should NOT depend on FastAPI (`Depends`)
3. Create own DB sessions/connections
4. Add corresponding README.md

```python
# Pattern
class NewService:
    def __init__(self):
        # Initialize without FastAPI dependencies
        self.db = get_db_session()  # Create own session

    async def do_work(self, params) -> Result:
        # Business logic
        pass
```

### Working with Pydantic Schemas

1. Check `src/models/schemas/` for existing schemas
2. Handle enum serialization carefully (use `change_type_str` pattern)
3. Add validators for type normalization
4. Test serialization round-trips

```python
# Pattern for safe enum access after deserialization
@property
def change_type_str(self) -> str:
    """Get change_type as string, handling both enum and string types."""
    if isinstance(self.change_type, ChangeType):
        return self.change_type.value
    return self.change_type
```

### Adding a New API Route

1. Read `src/api/fastapi/routes/README.md`
2. Check existing routes for patterns
3. Use Pydantic schemas for request/response validation
4. Add tests in `tests/api/fastapi/routes/`

## Key Patterns to Know

### 1. Activity Service Wrapper

Activities are thin wrappers around services:
```python
@activity.defn
async def activity_name(input_data: dict) -> dict:
    service = ServiceClass()
    result = await service.method(input_data["param"])
    return result.__dict__
```

### 2. Error Classification

```python
# Non-retryable: auth errors, not found, validation
if any(x in error for x in ["401", "403", "404", "unauthorized"]):
    raise ApplicationError(msg, non_retryable=True)

# Retryable: network, rate limits, transient
raise ApplicationError(msg)  # Will retry
```

### 3. Workflow Cleanup Pattern

```python
try:
    result = await workflow.execute_activity(...)
finally:
    if clone_path:
        await workflow.execute_activity(cleanup_activity, clone_path)
```

### 4. LangGraph State Flow

```python
# Each node modifies state and returns updated state
async def invoke(self, state: dict) -> dict:
    new_data = await self.process(state["input"])
    return {**state, "output": new_data}
```

### 5. Neo4j Query Pattern

```python
# Use KGQueryService for all Neo4j operations
service = KGQueryService()
candidates = await service.get_symbol_relationships(
    repo_id=repo_id,
    symbol_names=symbol_names,
    max_hops=1
)
```

## File Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Activity | `*_activities.py` | `pr_review_activities.py` |
| Workflow | `*_workflow.py` | `pr_review_workflow.py` |
| Worker | `*_worker.py` | `pr_review_worker.py` |
| LangGraph node | Descriptive name | `seed_analyzer.py`, `context_ranker.py` |
| Service | `*_service.py` or descriptive | `kg_query_service.py` |
| Schema | Descriptive | `pr_patch.py`, `seed_set.py` |
| Test | `test_*.py` | `test_pr_review_activities.py` |

## Important Files by Function

### Entry Points
- `src/main.py` - FastAPI application startup
- `src/workers/pr_review_worker.py` - PR review worker process
- `src/workers/repo_indexing_worker.py` - Indexing worker process

### Configuration
- `src/core/config.py` - Environment configuration
- `src/core/pr_review_config.py` - PR review pipeline config
- `src/core/database.py` - PostgreSQL connection
- `src/core/neo4j.py` - Neo4j connection

### Core Schemas
- `src/models/schemas/pr_review/pr_patch.py` - PR diff representation
- `src/models/schemas/pr_review/seed_set.py` - Seed symbols from diff
- `src/models/schemas/pr_review/context_pack.py` - Assembled context
- `src/models/schemas/pr_review/review_output.py` - Generated review

### Exception Handling
- `src/exceptions/pr_review_exceptions.py` - PR review specific exceptions
- `src/utils/exception.py` - Base application exceptions

## Technology Quick Reference

| Component | Technology | Key Files |
|-----------|------------|-----------|
| API Framework | FastAPI | `src/api/fastapi/` |
| Workflow Orchestration | Temporal | `src/workflows/`, `src/activities/` |
| AI Reasoning | LangGraph | `src/langgraph/` |
| Code Analysis | Tree-sitter | `src/parser/` |
| Knowledge Graph | Neo4j | `src/services/kg/` |
| Database | PostgreSQL + pgVector | `src/core/database.py` |
| LLM | Claude/Gemini | `src/services/llm/` |
| Validation | Pydantic | `src/models/schemas/` |

## Debugging Common Issues

### "No module named 'tree_sitter'"
- Install tree-sitter: `poetry install`
- Tree-sitter is an optional dependency for local testing

### Activity serialization errors
- Ensure all return values are JSON-serializable (dicts, not objects)
- Use `model_dump()` for Pydantic models
- Convert enums to values explicitly

### "change_type.value" AttributeError
- Use `change_type_str` property instead of `.value`
- Add pre-validator to normalize enum/string types
- See `src/models/schemas/pr_review/pr_patch.py` for pattern

### Neo4j connection issues
- Check `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` env vars
- Ensure Neo4j container is running: `docker compose up neo4j`

### Temporal workflow failures
- Check worker logs: `docker compose logs -f worker`
- Ensure activities are registered with worker
- Check for determinism violations (no random, no time, no I/O)

## Notes for Agents

- **Local file access**: Always read docs from file system, not hosted URLs
- **Check existing code**: Search for similar implementations before creating new ones
- **Follow patterns**: Use existing code as templates for consistency
- **Test coverage**: Add tests for new code in `tests/` mirroring `src/` structure
- **Validation**: Use Pydantic schemas at all boundaries
- **Error handling**: Always classify errors as retryable or non-retryable
