import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routers import clients, items, packing, reception, orders, config, consulting, labels, simplified_movements, abastecimento
from app.sap_integrator.lifecycle import start_integrator, stop_integrator
from app.sap_integrator.routers.api import router as sap_integrator_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_integrator()
    try:
        yield
    finally:
        stop_integrator()

app = FastAPI(
    title="Warehouse API",
    description="API de gestão de receção de mercadoria",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc) or "Erro interno no servidor"},
    )

routers = [
    clients.router,
    items.router,
    packing.router,
    reception.router,
    orders.router,
    config.router,
    consulting.router,
    labels.router,
    simplified_movements.router,
    abastecimento.router,
]

for router in routers:
    app.include_router(router)
    app.include_router(router, prefix="/api")

app.include_router(sap_integrator_router, prefix="/sap-b1")
app.include_router(sap_integrator_router, prefix="/api/sap-b1")

@app.get("/health")
def health():
    return {"status": "ok"}


def _frontend_dist_dir() -> Path:
    configured_path = os.getenv("FRONTEND_DIST_DIR")
    if configured_path:
        return Path(configured_path)

    return Path(__file__).resolve().parents[3] / "wms-app" / "dist"


frontend_dist = _frontend_dist_dir()
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

    @app.get("/")
    def frontend_index():
        return FileResponse(frontend_dist / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_spa(full_path: str):
        asset_path = frontend_dist / full_path
        if asset_path.is_file():
            return FileResponse(asset_path)

        return FileResponse(frontend_dist / "index.html")
