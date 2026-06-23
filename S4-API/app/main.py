from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import swagger_ui_bundle

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
from app.inbound_logging import configure_by_ptl_inbound_logging
from app.services.by_ptl_queue import register_by_ptl_queue_worker
from app.security import require_api_key


def create_application() -> FastAPI:
    app = FastAPI(
        title="S4-API",
        description="FastAPI base service for the S4-Log project.",
        version="0.1.0",
        openapi_version="3.0.3",
        swagger_ui_parameters={"persistAuthorization": True},
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    configure_by_ptl_inbound_logging(app)
    register_by_ptl_queue_worker(app)

    protected = {"dependencies": [Depends(require_api_key)]}
    app.include_router(health_router, **protected)
    app.include_router(business_partners_router, **protected)
    app.include_router(by_ptl_router, **protected)
    app.include_router(client_orders_router, **protected)
    app.include_router(itemmaster_router, **protected)
    app.include_router(production_control_router, **protected)
    app.include_router(production_setup_router, **protected)
    app.include_router(sales_summary_router, **protected)
    app.include_router(sales_summary_ma_router, **protected)
    app.include_router(settings_router, **protected)
    app.include_router(logistic_tables_router, **protected)
    app.include_router(workflow_router, **protected)

    app.mount("/swagger-static", StaticFiles(directory=swagger_ui_bundle.swagger_ui_path), name="swagger-static")

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="S4-API",
            swagger_js_url="/swagger-static/swagger-ui-bundle.js",
            swagger_css_url="/swagger-static/swagger-ui.css",
        )

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_schema() -> JSONResponse:
        schema = app.openapi()
        schema["openapi"] = "3.0.3"
        return JSONResponse(schema)

    return app


app = create_application()
