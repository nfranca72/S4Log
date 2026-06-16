"""FastAPI dependency injection helpers."""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.master import AsyncSessionLocal, get_master_db
from app.db.tenant_manager import get_tenant_session
from app.models.master import Company, User
from app.schemas.auth import UserOut

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    master_db: AsyncSession = Depends(get_master_db),
) -> UserOut:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        email: str = payload.get("sub")
        tenant_id: str = payload.get("tenant_id")
        if not email or not tenant_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate token")

    result = await master_db.execute(
        select(User).where(User.email == email, User.tenant_id == tenant_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return UserOut.model_validate(user)


async def get_current_admin(current_user: UserOut = Depends(get_current_user)) -> UserOut:
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return current_user


async def get_tenant_db(
    request: Request,
    master_db: AsyncSession = Depends(get_master_db),
) -> AsyncGenerator[AsyncSession, None]:
    tenant_id: str = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tenant not identified")

    result = await master_db.execute(
        select(Company).where(Company.tenant_id == tenant_id, Company.is_active == True)
    )
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant '{tenant_id}' not found or inactive")

    async for session in get_tenant_session(company.db_url, tenant_id):
        yield session
