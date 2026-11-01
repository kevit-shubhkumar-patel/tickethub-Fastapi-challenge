from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.auth import current_user
from app.db.client import get_db
from app.models.auth import CurrentUser, TokenResponse
from app.models.user import UserRead, UserRegister
from app.repositories.user_repo import UserRepository
from app.routers.users import get_user_service
from app.services.auth_service import AuthService
from app.services.user_service import UserService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service() -> AuthService:
    return AuthService(UserRepository(get_db()))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, svc: UserService = Depends(get_user_service)):
    return await svc.register(body)


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), svc: AuthService = Depends(get_auth_service)):
    return await svc.login(form.username, form.password)  # "username" holds the email


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser = Depends(current_user), svc: UserService = Depends(get_user_service)):
    return await svc.get(user.id)