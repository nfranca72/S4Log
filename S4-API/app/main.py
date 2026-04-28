from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.business_partners import router as business_partners_router
from app.routers.health import router as health_router
from app.routers.itemmaster import router as itemmaster_router
from app.routers.production_control import router as production_control_router


def create_application() -> FastAPI:
    app = FastAPI(
        title="S4-API",
        description="FastAPI base service for the S4-Log project.",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(business_partners_router)
    app.include_router(itemmaster_router)
    app.include_router(production_control_router)

    return app


app = create_application()
