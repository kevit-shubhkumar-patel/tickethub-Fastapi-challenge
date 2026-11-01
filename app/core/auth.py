from datetime import UTC, datetime

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.core.errors import AppError
from app.core.security import BEARER, decode_access_token
from app.db.client import get_db
from app.models.auth import CurrentUser
from app.repositories.user_repo import UserRepository

# tokenUrl tells Swagger where to log in; auto_error=False so *we* raise the error (in our envelope)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def current_user(token: str | None = Depends(oauth2_scheme)) -> CurrentUser:
    if not token:
        raise AppError(401, "NOT_AUTHENTICATED", "Missing bearer token", BEARER)
    claims = decode_access_token(token)

    user = await UserRepository(get_db()).get(claims["sub"])
    if not user or not user["is_active"]:
        raise AppError(401, "INVALID_TOKEN", "User no longer active", BEARER)

    return CurrentUser(
        id=user["id"], email=user["email"], name=user["name"], role=user["role"],
        jti=claims["jti"], token_exp=datetime.fromtimestamp(claims["exp"], UTC),
    )