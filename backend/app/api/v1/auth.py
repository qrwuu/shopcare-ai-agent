# app/api/v1/auth.py
"""认证 API - 账号密码登录与消费者注册。"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from typing import Optional
from app.core.security import create_access_token, get_current_user_id
from app.core.database import async_session_maker
from app.models.user import User
from app.services.demo_data import ensure_demo_orders_for_user
from sqlmodel import select

router = APIRouter()

DEMO_ACCOUNT = "10000001"
DEMO_PASSWORD = "123456"
DEMO_LEGACY_USERNAME = "test_user"


class LoginRequest(BaseModel):
    """账号密码登录请求。"""
    username: str = Field(..., min_length=8, max_length=8, pattern=r"^\d{8}$", description="8 位数字账号")
    password: str = Field(..., min_length=6, description="密码")


class RegisterRequest(BaseModel):
    """消费者注册请求。账号由系统自动生成。"""
    nickname: str = Field(..., min_length=1, max_length=100, description="昵称")
    password: str = Field(..., min_length=6, description="密码")


class TokenResponse(BaseModel):
    """Token 响应。"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    full_name: str
    is_admin: bool


class UserInfoResponse(BaseModel):
    """用户信息响应。"""
    user_id: int
    username: str
    email: str
    full_name: str
    phone: Optional[str]
    is_admin: bool
    created_at: str


def _token_response(user: User, username_override: Optional[str] = None) -> TokenResponse:
    token = create_access_token(user_id=user.id, is_admin=user.is_admin)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=username_override or user.username,
        full_name=user.full_name,
        is_admin=user.is_admin,
    )


async def _find_demo_user(session):
    result = await session.execute(select(User).where(User.username == DEMO_LEGACY_USERNAME))
    user = result.scalar_one_or_none()
    if user:
        return user, DEMO_ACCOUNT

    result = await session.execute(select(User).where(User.username == DEMO_ACCOUNT))
    user = result.scalar_one_or_none()
    if user:
        return user, None
    return None, None


async def _next_numeric_account(session) -> str:
    result = await session.execute(select(User.username))
    usernames = set(result.scalars().all())
    candidate = 10000002
    while str(candidate).zfill(8) in usernames:
        candidate += 1
    return str(candidate).zfill(8)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """使用 8 位账号和密码登录。"""
    async with async_session_maker() as session:
        username = request.username.strip()

        if username == DEMO_ACCOUNT:
            demo_user, username_override = await _find_demo_user(session)
            if request.password == DEMO_PASSWORD and demo_user and demo_user.is_active:
                return _token_response(demo_user, username_override=username_override)
            if demo_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="密码不正确，请重新输入。",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="账号不存在，请检查 8 位账号。",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.verify_password(request.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="密码不正确，请重新输入。",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系平台客服")

        return _token_response(user)


@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest):
    """注册消费者账号：系统生成唯一 8 位数字账号。"""
    async with async_session_maker() as session:
        account = await _next_numeric_account(session)
        user = User(
            username=account,
            password_hash=User.hash_password(request.password),
            email=f"{account}@shopcare.local",
            full_name=request.nickname.strip(),
            phone=None,
            is_admin=False,
            is_active=True,
        )

        session.add(user)
        await session.flush()
        await ensure_demo_orders_for_user(session, user)
        await session.commit()
        await session.refresh(user)

        return _token_response(user)


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(current_user_id: int = Depends(get_current_user_id)):
    """获取当前登录用户信息。"""
    async with async_session_maker() as session:
        user = await session.get(User, current_user_id)

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

        username = DEMO_ACCOUNT if user.username == DEMO_LEGACY_USERNAME else user.username
        return UserInfoResponse(
            user_id=user.id,
            username=username,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            is_admin=user.is_admin,
            created_at=user.created_at.isoformat(),
        )
