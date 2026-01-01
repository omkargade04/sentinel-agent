# API Routes Module

## What

The routes module defines FastAPI endpoints for the AI Code Reviewer backend. It provides RESTful APIs for repository indexing, GitHub integration, user management, and health checks.

## Why

API routes are essential for:
- **External Interface**: Expose application functionality via HTTP
- **Workflow Triggering**: Initiate Temporal workflows for async operations
- **User Interaction**: Handle user authentication and repository selection
- **Webhook Processing**: Receive GitHub webhook events

## How

### Architecture

```
api/fastapi/routes/
├── indexing.py        # Repository indexing endpoints
├── github.py          # GitHub OAuth and webhooks
├── repository.py      # Repository management
├── user.py           # User authentication
├── health.py          # Health check endpoints
└── README.md         # This file
```

### Key Routes

#### 1. Indexing Routes (`indexing.py`)

**Purpose**: Trigger repository indexing workflows.

**Endpoints**:

- `POST /index`: Start repository indexing
  ```python
  @router.post("/index", response_model=IndexRepoResponse)
  async def index_repo(
      repo_request: IndexRepoRequest,
      temporal_client: Client = Depends(get_temporal_client),
      current_user: User = Depends(get_current_user)
  )
  ```
  
  **Request Body**:
  ```json
  {
    "installation_id": 12345,
    "github_repo_name": "owner/repo",
    "repo_id": "repo-uuid",
    "default_branch": "main",
    "repo_url": "https://github.com/owner/repo.git"
  }
  ```
  
  **Response**:
  ```json
  {
    "workflow_id": "repo-index-repo-uuid-main",
    "run_id": "run-uuid",
    "message": "Indexing started for repository owner/repo"
  }
  ```
  
  **Flow**:
  ```
  1. Validate user has access to installation
  2. Generate workflow ID: repo-index-{repo_id}-{branch}
  3. Start Temporal workflow: RepoIndexingWorkflow.run
  4. Return workflow handle for tracking
  ```

**Authentication**: Requires authenticated user via `get_current_user`

**Error Handling**:
- 401: Unauthorized (no valid session)
- 500: Workflow start failure

#### 2. GitHub Routes (`github.py`)

**Purpose**: Handle GitHub OAuth and webhook events.

**Endpoints**:

- `GET /github/auth`: Initiate OAuth flow
  ```python
  @router.get("/auth")
  async def github_auth(
      github_service: GithubService = Depends(GithubService)
  )
  ```
  
  **Flow**:
  ```
  1. Generate state token
  2. Redirect to GitHub OAuth URL
  3. User authorizes → GitHub redirects to /callback
  ```

- `GET /github/callback`: OAuth callback handler
  ```python
  @router.get("/callback")
  async def github_callback(
      code: str,
      state: str,
      github_service: GithubService = Depends(GithubService)
  )
  ```
  
  **Flow**:
  ```
  1. Exchange code for access token
  2. Fetch user data from GitHub
  3. Store/update user in database
  4. Redirect to GitHub App installation
  ```

- `POST /github/webhook`: Webhook event handler
  ```python
  @router.post("/webhook")
  async def github_webhook(
      request: Request,
      github_service: GithubService = Depends(GithubService)
  )
  ```
  
  **Headers**:
  - `X-GitHub-Event`: Event type (installation, pull_request, etc.)
  - `X-GitHub-Delivery`: Unique delivery ID
  - `X-Hub-Signature-256`: Webhook signature (for verification)
  
  **Flow**:
  ```
  1. Verify webhook signature (TODO: implement)
  2. Extract event type from headers
  3. Parse JSON payload
  4. Route to GithubService.process_webhook()
  5. Return success response
  ```

#### 3. Repository Routes (`repository.py`)

**Purpose**: Manage repository listings and selections.

**Endpoints**:

- `GET /repositories`: Get all repositories from GitHub
  ```python
  @router.get("/repositories")
  async def get_repositories(
      current_user: User = Depends(get_current_user),
      service: RepositoryService = Depends(RepositoryService)
  )
  ```
  
  **Response**: List of repositories from GitHub API

- `GET /repositories/selected`: Get user's selected repositories
  ```python
  @router.get("/repositories/selected")
  async def get_selected_repos(
      current_user: User = Depends(get_current_user),
      service: RepositoryService = Depends(RepositoryService)
  )
  ```
  
  **Response**: List of repositories from database

#### 4. User Routes (`user.py`)

**Purpose**: User authentication and management.

**Endpoints**:
- User registration/login endpoints
- User profile management

#### 5. Health Routes (`health.py`)

**Purpose**: System health and readiness checks.

**Endpoints**:
- `GET /health`: Basic health check
- `GET /ready`: Readiness check (dependencies available)

### Request/Response Models

**IndexRepoRequest**:
```python
class IndexRepoRequest(BaseModel):
    installation_id: int
    github_repo_name: str
    repo_id: str
    default_branch: str
    repo_url: Optional[str] = None
```

**IndexRepoResponse**:
```python
class IndexRepoResponse(BaseModel):
    workflow_id: str
    run_id: str
    message: str
```

### Middleware Integration

**Authentication** (`middlewares/auth.py`):
- `get_current_user`: Validates user session
- Extracts user from JWT token or session cookie
- Returns `User` model or raises 401

**GitHub Middleware** (`middlewares/github.py`):
- Webhook signature verification (if implemented)
- Request logging

**Temporal Client** (`core/temporal_client.py`):
- `get_temporal_client`: Provides Temporal client instance
- Handles connection management

### Error Handling

**HTTP Exceptions**:
- `HTTPException`: Standard FastAPI exceptions
- `401 Unauthorized`: Authentication required
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server errors

**Custom Exceptions**:
- `AppException`: Application-specific errors
- `UserNotFoundError`: User not found
- `BadRequestException`: Invalid request data

### Route Registration

**Main App** (`api/fastapi/__init__.py`):
```python
def register_routes(app: FastAPI):
    app.include_router(indexing.router, prefix="/api")
    app.include_router(github.router, prefix="/api")
    app.include_router(repository.router, prefix="/api")
    # ...
```

### Usage Examples

**Start Indexing**:
```bash
curl -X POST http://localhost:8000/api/index \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "installation_id": 12345,
    "github_repo_name": "owner/repo",
    "repo_id": "repo-uuid",
    "default_branch": "main"
  }'
```

**Get Repositories**:
```bash
curl http://localhost:8000/api/repositories \
  -H "Authorization: Bearer <token>"
```

**GitHub Webhook**:
```bash
curl -X POST http://localhost:8000/api/github/webhook \
  -H "X-GitHub-Event: installation" \
  -H "Content-Type: application/json" \
  -d '{...webhook payload...}'
```

### Design Decisions

1. **Async Endpoints**: All endpoints are async for better concurrency
2. **Dependency Injection**: Services injected via FastAPI Depends
3. **Response Models**: Pydantic models for validation
4. **Workflow Triggering**: Indexing is async via Temporal workflows
5. **Authentication**: Middleware-based auth on protected routes

### Dependencies

- **FastAPI**: Web framework
- **Pydantic**: Request/response validation
- **Temporal**: Workflow orchestration client
- **SQLAlchemy**: Database access (via services)

### Configuration

- API prefix: `/api` (configurable)
- CORS: Configured in main app
- Rate limiting: (Future enhancement)

### Testing

```python
# Test indexing endpoint
async def test_index_repo(client, auth_token):
    response = await client.post(
        "/api/index",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={
            "installation_id": 123,
            "github_repo_name": "test/repo",
            "repo_id": "test-uuid",
            "default_branch": "main"
        }
    )
    assert response.status_code == 200
    assert "workflow_id" in response.json()

# Test webhook
async def test_github_webhook(client):
    response = await client.post(
        "/api/github/webhook",
        headers={"X-GitHub-Event": "installation"},
        json={"action": "created", "installation": {...}}
    )
    assert response.status_code == 200
```

### Future Enhancements

- [ ] Webhook signature verification
- [ ] Rate limiting per user/IP
- [ ] Request logging/monitoring
- [ ] API versioning
- [ ] OpenAPI/Swagger documentation
- [ ] GraphQL endpoint for complex queries

