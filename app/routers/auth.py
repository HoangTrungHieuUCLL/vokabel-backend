from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import create_access_token, get_current_user, verify_password
from app.config import settings
from app.schemas import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    if body.username != settings.APP_USERNAME or not verify_password(
        body.password, settings.APP_PASSWORD_HASH
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return TokenResponse(access_token=create_access_token(body.username))


@router.get("/me", response_model=UserOut)
def me(username: str = Depends(get_current_user)) -> UserOut:
    return UserOut(username=username)
