"""Dynamic per-tenant async engine pool.

Engines are created on first access and cached for the lifetime of the process.
To invalidate (e.g. after a tenant DB URL change) call `evict_tenant(tenant_id)`.
"""

import asyncio
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_engines: dict[str, any] = {}
_lock = asyncio.Lock()


async def _get_engine(db_url: str, tenant_id: str):
    async with _lock:
        if tenant_id not in _engines:
            engine = create_async_engine(
                db_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )
            _engines[tenant_id] = engine
    return _engines[tenant_id]


async def get_tenant_session(db_url: str, tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    engine = await _get_engine(db_url, tenant_id)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


def evict_tenant(tenant_id: str) -> None:
    """Remove a tenant engine from the pool (does not close existing connections)."""
    _engines.pop(tenant_id, None)
