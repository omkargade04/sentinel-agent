from fastapi import APIRouter, Depends, Response, Cookie
from typing import Optional

from src.api.fastapi.middlewares.auth import IsAuthenticated
from src.models.db.users import User
from src.models.schemas.users import UserLogin, UserRegister
from src.services.users.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        samesite="strict",
        secure=True,
        max_age=60 * 15,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=True,
        max_age=60 * 60 * 24 * 7,
    )


@router.post("/register")
async def register(
    register_request: UserRegister,
    response: Response,
    user_service: UserService = Depends(UserService),
):
    """
    User registration endpoint.
    On success, sets access and refresh tokens as HttpOnly cookies.
    """
    token_data = user_service.register(register_request)
    set_auth_cookies(
        response,
        token_data["access_token"],
        token_data["refresh_token"]
    )
    return {"status": "success", "message": token_data["message"]}


@router.post("/login")
async def login(
    login_request: UserLogin,
    response: Response,
    user_service: UserService = Depends(UserService),
):
    """
    User login endpoint
    On success, sets access and refresh tokens as HttpOnly cookies.
    """
    token_data = user_service.login(login_request)
    set_auth_cookies(
        response,
        token_data["access_token"],
        token_data["refresh_token"]
    )
    return {"status": "success", "message": "Logged in successfully"}


@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    user_service: UserService = Depends(UserService),
):
    """
    Token refresh endpoint.
    Uses the refresh_token from cookies to get new tokens.
    """
    token_data = user_service.refresh_token(refresh_token)
    set_auth_cookies(
        response,
        token_data["access_token"],
        token_data["refresh_token"]
    )
    return {"status": "success", "message": "Tokens refreshed"}


@router.get("/me")
async def me(
    authenticated_user: User = Depends(IsAuthenticated),
    user_service: UserService = Depends(UserService),
):
    """
    Get the profile for the currently authenticated user.
    """
    return user_service.me(authenticated_user)

@router.post('/logout')
async def logout(
    response: Response,
    user_service: UserService = Depends(UserService),
    authenticated_user: User = Depends(IsAuthenticated),
):
    """
    Logout the currently authenticated user.
    """
    user_service.logout(authenticated_user)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return {"status": "success", "message": "Logged out successfully"}