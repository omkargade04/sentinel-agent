# Repository Service Module

## What

The repository service module provides business logic for managing repository metadata and interactions with GitHub's repository API. It handles fetching repository lists, managing repository selections, and coordinating with GitHub installations.

## Why

Repository management is essential for:
- **Repository Discovery**: Fetching available repositories from GitHub installations
- **User Selection**: Managing which repositories users want to index/review
- **Metadata Synchronization**: Keeping repository metadata in sync with GitHub
- **Installation Integration**: Linking repositories to GitHub App installations

## How

### Architecture

```
services/repository/
├── repository_service.py    # Main repository business logic
├── helpers.py               # GitHub API utilities (token generation)
└── README.md               # This file
```

### Key Components

#### 1. RepositoryService (`repository_service.py`)

**Purpose**: Manages repository operations and GitHub API interactions.

**Key Methods**:

- `get_all_repositories(current_user)`: Fetches all repositories from GitHub
  ```python
  repos = await service.get_all_repositories(current_user)
  # Returns: List[RepositoryRead] with GitHub repository data
  ```
  
  **Flow**:
  ```
  1. Get user's GitHub installation
  2. Generate installation token via RepositoryHelpers
  3. Fetch repositories from GitHub API: GET /installation/repositories
  4. Parse and return repository list
  ```

- `get_user_selected_repositories(current_user)`: Gets repositories from database
  ```python
  repos = service.get_user_selected_repositories(current_user)
  # Returns: List[RepositoryRead] from local database
  ```
  
  **Flow**:
  ```
  1. Get user's GitHub installation
  2. Query Repository table filtered by installation_id
  3. Return repository records
  ```

**Key Features**:
- **Installation Scoping**: All operations scoped to user's installation
- **Error Handling**: Comprehensive error handling with user-friendly messages
- **Database Integration**: Uses SQLAlchemy for repository queries

#### 2. RepositoryHelpers (`helpers.py`)

**Purpose**: Provides utilities for GitHub App authentication and token management.

**Key Methods**:

- `generate_jwt_token()`: Creates JWT for GitHub App authentication
  ```python
  jwt_token = helpers.generate_jwt_token()
  # Returns: JWT string signed with GitHub App private key
  ```
  
  **Flow**:
  ```
  1. Get GitHub App ID and private key from settings
  2. Create JWT payload with:
     - iat: Current timestamp
     - exp: Current + 10 minutes
     - iss: GitHub App ID
  3. Sign with RS256 algorithm
  4. Return JWT token
  ```

- `generate_installation_token(installation_id)`: Mints installation access token
  ```python
  token = await helpers.generate_installation_token(12345)
  # Returns: Installation access token (valid 1 hour)
  ```
  
  **Flow**:
  ```
  1. Generate JWT token using generate_jwt_token()
  2. POST to GitHub API: /app/installations/{id}/access_tokens
  3. Extract token from response
  4. Return installation token
  ```

**Security**:
- **JWT Expiration**: Tokens expire in 10 minutes
- **Installation Tokens**: Short-lived (1 hour) per GitHub's API
- **Private Key**: Stored securely, never logged

### Data Models

**RepositoryRead** (Schema):
```python
{
    "id": str,                    # Internal UUID
    "github_repo_id": int,         # GitHub repository ID
    "github_repo_name": str,       # Repository name
    "full_name": str,              # owner/repo
    "private": bool,               # Is private repo
    "default_branch": str,         # Default branch name
    "installation_id": int,       # GitHub installation ID
    "created_at": datetime,
    "updated_at": datetime,
    "last_indexed_sha": str,      # Last indexed commit SHA
    "last_indexed_at": datetime   # Last indexing timestamp
}
```

**Repository** (Database Model):
- Maps to `repositories` table
- Linked to `github_installations` via `installation_id`
- Tracks indexing metadata (`last_indexed_sha`, `last_indexed_at`)

### Integration Points

**With GitHub Service**:
- Receives repository data from `InstallationService` webhook processing
- Uses same `Repository` model for consistency

**With Indexing Service**:
- Provides repository metadata for indexing workflows
- Updates `last_indexed_sha` and `last_indexed_at` after indexing

**With Temporal Workflows**:
- Repository metadata passed to indexing workflows
- Installation ID used for token generation in activities

### Error Handling

**UserNotFoundError**: No GitHub installation found for user
```python
if not current_user.github_installations:
    raise UserNotFoundError("No GitHub installation found")
```

**AppException**: Wrapped exceptions with status codes
- 500: Unexpected errors
- 401/403: Authentication failures
- 404: Repository not found

**Database Errors**: SQLAlchemy errors caught and wrapped

### Usage Examples

**Fetch All Repositories**:
```python
from src.services.repository.repository_service import RepositoryService
from src.core.database import get_db

@router.get("/repositories")
async def get_repositories(
    current_user: User = Depends(get_current_user),
    service: RepositoryService = Depends(RepositoryService)
):
    repos = await service.get_all_repositories(current_user)
    return repos
```

**Get Selected Repositories**:
```python
@router.get("/repositories/selected")
async def get_selected_repos(
    current_user: User = Depends(get_current_user),
    service: RepositoryService = Depends(RepositoryService)
):
    repos = service.get_user_selected_repositories(current_user)
    return repos
```

**Generate Installation Token** (in activities):
```python
from src.services.repository.helpers import RepositoryHelpers

@activity.defn
async def clone_repo_activity(repo_request: dict):
    helpers = RepositoryHelpers()
    token = await helpers.generate_installation_token(
        repo_request["installation_id"]
    )
    # Use token for git operations
```

### Design Decisions

1. **Separation of Concerns**: Service handles business logic, helpers handle GitHub API
2. **No DB Dependency in Helpers**: RepositoryHelpers works in Temporal context
3. **Installation Scoping**: All operations scoped to user's installation
4. **Token Caching**: (Future) Could cache tokens to reduce API calls

### Dependencies

- **httpx**: For async HTTP requests to GitHub API
- **jwt**: For JWT token generation
- **SQLAlchemy**: For database queries
- **FastAPI**: For dependency injection (in routes)

### Configuration

Required settings:
- `GITHUB_APP_ID`: GitHub App ID
- `GITHUB_APP_PRIVATE_KEY`: Private key for JWT signing
- Database connection for repository queries

### GitHub API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/installation/repositories` | GET | Fetch all repos for installation |
| `/app/installations/{id}/access_tokens` | POST | Generate installation token |
| `/user` | GET | Get user info (via OAuth token) |

### Testing

```python
# Test repository fetching
async def test_get_all_repositories():
    service = RepositoryService(db=test_db)
    repos = await service.get_all_repositories(test_user)
    assert len(repos) > 0
    assert all("full_name" in repo for repo in repos)

# Test token generation
async def test_generate_installation_token():
    helpers = RepositoryHelpers()
    token = await helpers.generate_installation_token(12345)
    assert token is not None
    assert len(token) > 0

# Test JWT generation
def test_generate_jwt_token():
    helpers = RepositoryHelpers()
    jwt = helpers.generate_jwt_token()
    assert jwt is not None
    # Verify JWT structure
    parts = jwt.split(".")
    assert len(parts) == 3  # header.payload.signature
```

### Future Enhancements

- [ ] Repository search/filtering
- [ ] Repository selection UI integration
- [ ] Token caching with expiration
- [ ] Rate limiting for GitHub API calls
- [ ] Repository metadata refresh scheduling
- [ ] Bulk repository operations

