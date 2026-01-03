# GitHub Service Module

## What

The GitHub service module handles all interactions with GitHub's API, including OAuth authentication, GitHub App installations, and webhook processing. It serves as the primary interface between the application and GitHub's services.

## Why

GitHub integration is essential for:
- **User Authentication**: OAuth flow to authenticate users via GitHub
- **Repository Access**: GitHub App installations provide secure, scoped access to user repositories
- **Webhook Processing**: Real-time event handling for installation changes, repository updates, and PR events
- **Token Management**: Secure generation and management of installation tokens for API access

## How

### Architecture

```
services/github/
├── github_service.py          # Main GitHub API integration
├── installation_service.py    # GitHub App installation management
├── helpers.py                 # Shared utilities (if exists)
└── README.md                 # This file
```

### Key Components

#### 1. GithubService (`github_service.py`)

**Purpose**: Handles OAuth authentication flow and webhook event routing.

**Key Methods**:

- `handle_auth()`: Initiates GitHub OAuth flow
  - Generates secure state token
  - Redirects user to GitHub authorization page
  - Returns redirect response with OAuth URL

- `handle_callback(code, state)`: Processes OAuth callback
  - Exchanges authorization code for access token
  - Fetches user data from GitHub API
  - Redirects to GitHub App installation page
  - Returns redirect response

- `process_webhook(body, event_type)`: Routes webhook events
  - Validates webhook payload
  - Routes to appropriate handler based on event type
  - Returns processing status

**Flow**:
```
User → /github/auth → GitHub OAuth → /github/callback → 
Exchange Code → Get User → Redirect to Installation → 
User Installs App → Webhook Received → process_webhook()
```

#### 2. InstallationService (`installation_service.py`)

**Purpose**: Manages GitHub App installation lifecycle and associated repositories.

**Key Methods**:

- `process_installation_created(payload)`: Handles new installations
  - Creates `GithubInstallation` record in database
  - Processes associated repositories from payload
  - Links installation to user account
  - Updates timestamps

- `process_installation_deleted(payload)`: Handles installation removal
  - Marks installation as deleted
  - Logs affected repositories
  - Updates database records

- `process_repositories_changed(payload)`: Handles repository additions/removals
  - Processes `repositories_added` list
  - Processes `repositories_removed` list
  - Creates/updates `Repository` records
  - Maintains installation-repository relationships

**Database Models**:
- `GithubInstallation`: Stores installation metadata
- `Repository`: Stores repository information linked to installations

### Webhook Event Types

| Event Type | Actions Handled | Description |
|------------|----------------|-------------|
| `installation` | `created`, `deleted` | App installation lifecycle |
| `installation_repositories` | `added`, `removed` | Repository access changes |
| `pull_request` | (TODO) | PR events for code reviews |

### Security Considerations

1. **State Token**: Random hex token prevents CSRF attacks in OAuth flow
2. **Installation Tokens**: Short-lived tokens (1 hour) minted per request
3. **Webhook Verification**: (Should be implemented) Verify webhook signatures
4. **Token Storage**: Access tokens stored securely, never logged

### Error Handling

- **OAuth Errors**: Wrapped in `AppException` with user-friendly messages
- **Webhook Errors**: Validation errors raise `BadRequestException`
- **Database Errors**: SQLAlchemy errors caught and wrapped appropriately

### Usage Example

```python
from src.services.github.github_service import GithubService
from src.core.database import get_db

# In FastAPI route
@router.get("/auth")
async def github_auth(
    github_service: GithubService = Depends(GithubService)
):
    return github_service.handle_auth()

# Webhook handler
@router.post("/webhook")
async def webhook(
    request: Request,
    github_service: GithubService = Depends(GithubService)
):
    event_type = request.headers.get("X-GitHub-Event")
    body = await request.json()
    return await github_service.process_webhook(body, event_type)
```

### Dependencies

- **FastAPI**: For dependency injection
- **httpx**: For async HTTP requests to GitHub API
- **SQLAlchemy**: For database operations
- **secrets**: For secure token generation

### Configuration

Required environment variables:
- `GITHUB_OAUTH_CLIENT_ID`: OAuth app client ID
- `GITHUB_OAUTH_CLIENT_SECRET`: OAuth app client secret
- `GITHUB_REDIRECT_URI`: OAuth callback URL
- `GITHUB_APP_NAME`: GitHub App name for installation URL

### Testing

```python
# Test OAuth flow
def test_github_auth():
    service = GithubService(db=test_db)
    response = service.handle_auth()
    assert isinstance(response, RedirectResponse)
    assert "github.com/login/oauth" in response.url

# Test webhook processing
async def test_installation_webhook():
    payload = {
        "action": "created",
        "installation": {"id": 123, "account": {...}},
        "repositories": [...]
    }
    service = GithubService(db=test_db)
    result = await service.process_webhook(payload, "installation")
    assert result["status"] == "success"
```

### Future Enhancements

- [ ] Webhook signature verification
- [ ] PR webhook handling for automated reviews
- [ ] Installation token caching
- [ ] Rate limiting for GitHub API calls
- [ ] Retry logic for transient failures

