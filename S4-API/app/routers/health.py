from fastapi import APIRouter, HTTPException

from app.db.connection import test_connection
from app.settings import settings

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Health check")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "S4-API"}


@router.get("/health/db", summary="Database connectivity check")
def database_health_check() -> dict[str, str]:
    try:
        test_connection()
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {exc}") from exc

    return {
        "status": "ok",
        "service": "S4-API",
        "database": settings.db_name or "configured-via-connection-string",
    }
