from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.settings import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _configured_api_key_hashes() -> list[str]:
    if settings.api_key_hashes:
        raw_hashes = settings.api_key_hashes.replace(";", ",").split(",")
        return [value.strip().lower() for value in raw_hashes if value.strip()]

    if settings.api_key:
        return [sha256(settings.api_key.encode("utf-8")).hexdigest()]

    return []


def require_api_key(api_key: Optional[str] = Security(api_key_header)) -> None:
    configured_hashes = _configured_api_key_hashes()
    if not configured_hashes:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key authentication is not configured",
        )

    supplied_hash = sha256((api_key or "").encode("utf-8")).hexdigest()
    if not api_key or not any(compare_digest(supplied_hash, hash_value) for hash_value in configured_hashes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
