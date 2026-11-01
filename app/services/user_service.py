from fastapi.concurrency import run_in_threadpool
from pymongo.errors import DuplicateKeyError
from app.core.errors import AppError, NotFound
from app.models.common import Page
from app.models.user import UserCreate, UserRead, UserUpdate,UserRegister,Role
from app.repositories.user_repo import UserRepository
from app.core.security import hash_password

class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    async def create(self, data: UserCreate) -> UserRead:
        payload = data.model_dump()
        payload["email"] = payload["email"].lower()
        try:
            doc = await self.repo.insert(payload)
        except DuplicateKeyError:
            raise AppError(409, "EMAIL_TAKEN", "A user with this email already exists")
        return UserRead(**doc)

    async def get(self, user_id: str) -> UserRead:
        doc = await self.repo.get(user_id)
        if not doc:
            raise NotFound("User")
        return UserRead(**doc)

    async def list(self, limit: int, cursor: str | None) -> Page[UserRead]:
        docs = await self.repo.list_page(limit + 1, cursor)  # +1 tells us if there's a next page
        has_more = len(docs) > limit
        docs = docs[:limit]
        return Page(items=[UserRead(**d) for d in docs],
                    next_cursor=docs[-1]["id"] if has_more else None)

    async def update(self, user_id: str, data: UserUpdate) -> UserRead:
        doc = await self.repo.update(user_id, data.model_dump(exclude_unset=True))
        if not doc:
            raise NotFound("User")
        return UserRead(**doc)

    async def delete(self, user_id: str) -> None:
        if not await self.repo.update(user_id, {"is_active": False}):
            raise NotFound("User")

    async def register(self, data: UserRegister) -> UserRead:
        payload = {
            "email": data.email.lower(),
            "name": data.name,
            "role": Role.attendee,                       # forced, never from the client
            "password_hash": await run_in_threadpool(hash_password, data.password),
        }
        try:
            doc = await self.repo.insert(payload)
        except DuplicateKeyError:
            raise AppError(409, "EMAIL_TAKEN", "A user with this email already exists")
        return UserRead(**doc)