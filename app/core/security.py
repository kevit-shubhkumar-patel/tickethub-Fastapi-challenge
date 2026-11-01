import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.errors import AppError

_hasher = PasswordHash.recommended()
ALGORITHM = "HS256"
BEARER = {"WWW-Authenticate": "Bearer"}


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _hasher.verify(plain, hashed)


# Used when the email doesn't exist, so a wrong email takes as long as a wrong password
DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def create_access_token(user_id: str, role: str, expires_delta: timedelta | None = None) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,                  # who
        "role": role,                    # what they are
        "jti": uuid.uuid4().hex,         # unique token id (used for logout in Step 7)
        "type": "access",
        "iat": now,
        "exp": now + (expires_delta or timedelta(minutes=settings.access_token_minutes)),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM],
                            options={"require": ["sub", "role", "jti", "exp"]})
    except jwt.ExpiredSignatureError:
        raise AppError(401, "TOKEN_EXPIRED", "Access token has expired", BEARER)
    except jwt.InvalidTokenError:
        raise AppError(401, "INVALID_TOKEN", "Access token is invalid", BEARER)
    if claims.get("type") != "access":
        raise AppError(401, "INVALID_TOKEN", "Access token is invalid", BEARER)
    return claims