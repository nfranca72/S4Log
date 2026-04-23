import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import clients, items, packing, reception, orders, config, consulting

app = FastAPI(
    title="Warehouse API",
    description="API de gestão de receção de mercadoria",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients.router)
app.include_router(items.router)
app.include_router(packing.router)
app.include_router(reception.router)
app.include_router(orders.router)
app.include_router(config.router)
app.include_router(consulting.router)

@app.get("/health")
def health():
    return {"status": "ok"}
