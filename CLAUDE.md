# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

S4-Log is a warehouse management (WMS) system integrating with SAP Business One, made of independently deployable sub-projects. There is no root build system — each sub-project has its own dependencies and is run separately.

```
S4-Log/
├── S4-API/                    FastAPI gateway to SAP B1 Service Layer (production/BY-PTL/sales)
├── S4-Portal/backend/         FastAPI multi-tenant B2B portal backend
├── S4toSCP/
│   ├── wms-app/                React (Vite) SPA — warehouse operator UI
│   └── wms-scpapp/
│       ├── backend/            FastAPI backend: reception, packing, labels, SAP B1 sync scheduler
│       └── rfid-bridge/        C# .NET 9 bridge to Zebra RFID readers
└── Utilities/                 ZPL/RFID helper scripts and the Zebra SDK DLLs
```

## Commands

### S4-API (`S4-API/`)
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Config via `.env` (copy from `.env.example`): DB connection (SQL Server/pyodbc), SAP B1 Service Layer credentials, BY-PTL external WMS integration, sales-summary email SMTP settings. Every route (except none) requires header `X-API-Key`; keys are validated as SHA-256 hashes via `API_KEY_HASHES` (see `app/security.py`).

### S4toSCP backend (`S4toSCP/wms-scpapp/backend/`)
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload   # or: ./run.sh
```
Config in `app/settings.py` (pydantic-settings, reads `.env`): SQL Server connection, RFID bridge URL/antenna config, Zebra printer TCP settings, label template dir. Serves the built `wms-app` frontend as static files from `../wms-app/dist` (override with `FRONTEND_DIST_DIR`), with SPA fallback routing.

### wms-app frontend (`S4toSCP/wms-app/`)
```bash
npm install
npm run dev        # http://localhost:3000, proxies /api/* -> http://127.0.0.1:8000
npm run build       # outputs to dist/, served by wms-scpapp backend
npm run preview
```

### rfid-bridge (`S4toSCP/wms-scpapp/rfid-bridge/`)
```bash
dotnet run
```
.NET 9 minimal API. `RfidBridge:Provider` in `appsettings.json` selects `Fake` (local dev/smoke tests) or `ZebraSdk` (real reader, Windows only, loads the Zebra Host RFID SDK DLL by reflection from `Utilities/ZebraSdk`).

### S4-Portal backend (`S4-Portal/backend/`)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python seed.py                 # creates tables + test data
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

No test suites currently exist in this repository.

## Architecture

### S4-API — SAP B1 gateway
Stateless FastAPI service, one router+service+repository triplet per domain (`business_partners`, `by_ptl`, `client_orders`, `itemmaster`, `logistic_tables`, `production_control`, `production_setup`, `sales_summary`, `sales_summary_ma`, `settings`, `workflow`). Talks to SQL Server directly via pyodbc and to SAP B1 via its Service Layer REST API (`app/services/sap_service_layer.py`).

- **BY-PTL** (Put-to-Light): a single external-WMS integration exposed at `POST /BY-PTL/BYPTL`, forwarding actions (`PTL_START`, `PTL_CHANGE`, `PACKING_LIST`, `PACKED_BOX`) to a customer-hosted WMS. Outbound events are queued in `dbo.SyncQueue` and drained by a background polling worker (`app/services/by_ptl_queue.py`, interval `BY_PTL_QUEUE_POLL_SECONDS`) with per-event idempotency and atomic claiming to avoid duplicate sends across concurrent workers.
- Custom Swagger UI is served from bundled static assets (`swagger_ui_bundle`) rather than the CDN, and `/docs`/`/openapi.json` are manually wired since FastAPI's defaults are disabled.
- Sales-summary email jobs read from a separate `SALES_DB_*` database/connection than the main API DB.

### wms-scpapp backend — warehouse operations + SAP sync
Two distinct halves under one FastAPI app (`app/main.py`):
1. **Warehouse routers** (`app/routers/`): clients, items, packing, reception, orders, config, consulting, labels, simplified_movements, abastecimento, benfica_items, separation_documents. Every router is mounted twice — bare and under `/api` — so the frontend can call either path.
2. **`app/sap_integrator/`**: a self-contained SAP B1 sync subsystem started/stopped via the app's `lifespan` (`lifecycle.py`). Uses APScheduler (`scheduler.py`) to periodically pull items, business partners, transfers, stock movements, purchase orders, and dashboard/account-balance data from SAP B1 Service Layer (`sap/service_layer.py`) into local SQL Server tables (`wms/sql_server.py`), through per-domain integration modules in `integrations/`. Exposed under `/sap-b1` and `/api/sap-b1`.

Label printing sends ZPL templates (`label_templates/*.zpl`, Jinja-style placeholders) directly over TCP to Zebra printers on port 9100 (`app/services/label_printing.py`). RFID tag reads flow through `app/services/rfid_bridge_client.py` / `rfid_listener.py`, which call the separate rfid-bridge HTTP/SSE service — supports up to two additional tunnel URLs (`RFID_BRIDGE_TUNNEL_1_URL`, `RFID_BRIDGE_TUNNEL_2_URL`) for multi-station setups.

The backend serves the frontend build directly (static files + SPA fallback in `main.py`) — in production these two are deployed together as one unit, even though they're developed separately.

### rfid-bridge — RFID hardware abstraction
Minimal ASP.NET Core API decoupling the Python backend from the RFID reader hardware. `IRfidProvider` (`Services/IRfidProvider.cs`) is implemented by `FakeRfidProvider` (deterministic mock, `POST /rfid/mock/tags`) and `ZebraSdkProvider` (loads the vendor DLL via reflection so the project doesn't need to reference it directly, tolerant of SDK property-name differences across versions). Provider choice and reader connection settings (host/port/antennas/power) live in `appsettings.json` under `RfidBridge:*`.

### wms-app — operator frontend
React 18 + Vite SPA, plain CSS Modules (no CSS framework), React Router for navigation. `src/services/api.js` centralizes all backend calls; `src/context/ToastContext.jsx` provides app-wide toast notifications. Pages under `src/pages/` map to warehouse workflows: CSV import, RFID reception, stock consultation, labels, SAP B1 status, config, abastecimento (replenishment), separation documents/execution, simplified stock movements. In dev, Vite proxies `/api/*` to the backend on port 8000 (no CORS setup needed locally); in production the backend serves the built `dist/` directly, so paths must work both proxied and unproxied.

### S4-Portal — multi-tenant B2B portal (early stage)
Separate FastAPI app, not yet integrated with the other services. Multi-tenant via subdomain: the `Host` header is parsed by `TenantMiddleware` to resolve a `tenant_id`, which selects a per-tenant PostgreSQL database from a connection pool (`app/db/`), distinct from a shared master DB (`s4log_master`) holding `companies`/`users`. Auth is JWT (HS256, `app/core/security.py`) carrying `sub` (email) + `tenant_id`. Routers live under `app/modules/<domain>/router.py` (currently `auth`, `companies`), mounted at `/api/v1`.

## Working across sub-projects

- S4-API and the wms-scpapp backend are separate services with separate SAP B1 connections/credentials and separate purposes: S4-API serves production-control/BY-PTL/sales-summary integrations for external callers (API-key protected), while wms-scpapp is the operator-facing warehouse app with its own SAP sync scheduler. Don't assume shared state or a shared DB connection between them.
- wms-app and wms-scpapp/backend are deployed as one unit (frontend build served by the backend) — changes to either should keep the `/api` prefix contract in `vite.config.js`'s proxy and `main.py`'s double router mounting in sync.
- rfid-bridge is a separate process/deployable from wms-scpapp backend, reached over HTTP — it exists as its own project specifically because it needs the Zebra SDK, which is Windows-only/.NET, unlike the rest of the Python stack.
