from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Role(StrEnum):
    admin = "admin"
    organizer = "organizer"
    staff = "staff"
    attendee = "attendee"


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields → 422
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    role: Role = Role.attendee


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for f in self.model_fields_set:
            if getattr(self, f) is None:
                raise ValueError(f"{f} cannot be null")
        return self

class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=128)

class UserRead(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime