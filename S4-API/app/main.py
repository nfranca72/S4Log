from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.business_partners import router as business_partners_router
from app.routers.by_ptl import router as by_ptl_router
from app.routers.client_orders import router as client_orders_router
from app.routers.health import router as health_router
from app.routers.itemmaster import router as itemmaster_router
from app.routers.logistic_tables import router as logistic_tables_router
from app.routers.production_control import router as production_control_router
from app.routers.production_setup import router as production_setup_router
from app.routers.sales_summary import router as sales_summary_router
from app.routers.sales_summary_ma import router as sales_summary_ma_router
from app.routers.settings import router as settings_router
from app.routers.workflow import router as workflow_router
from app.security import require_api_key


def create_application() -> FastAPI:
    app = FastAPI(
        title="S4-API",
        description="FastAPI base service for the S4-Log project.",
        version="0.1.0",
        dependencies=[Depends(require_api_key)],
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
    app.include_router(by_ptl_router)
    app.include_router(client_orders_router)
    app.include_router(itemmaster_router)
    app.include_router(production_control_router)
    app.include_router(production_setup_router)
    app.include_router(sales_summary_router)
    app.include_router(sales_summary_ma_router)
    app.include_router(settings_router)
    app.include_router(logistic_tables_router)
    app.include_router(workflow_router)

    return app


app = create_application()
