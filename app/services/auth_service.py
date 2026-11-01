from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import BEARER, DUMMY_HASH, create_access_token, verify_password
from app.models.auth import TokenResponse
from app.repositories.user_repo import UserRepository


class AuthService:
    def __init__(self, users: UserRepository):
        self.users = users

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.users.get_by_email(email.strip().lower())
        hashed = user.get("password_hash") if user else None

        # always run one verify, even for unknown emails (timing-safe)
        ok = await run_in_threadpool(verify_password, password, hashed or DUMMY_HASH)

        if not (user and hashed and ok and user["is_active"]):
            raise AppError(401, "INVALID_CREDENTIALS", "Incorrect email or password", BEARER)

        return TokenResponse(
            access_token=create_access_token(user["id"], user["role"]),
            expires_in=settings.access_token_minutes * 60,
        )