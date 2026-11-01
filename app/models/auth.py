from datetime import datetime
from pydantic import BaseModel
from app.models.user import Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class CurrentUser(BaseModel):
    id: str
    email: str
    name: str
    role: Role
    jti: str
    token_exp: datetime