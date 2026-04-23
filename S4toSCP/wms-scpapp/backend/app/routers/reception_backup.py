from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.models.schemas import (
    PackingListSummary, BoxSummary, BoxDetail,
    WarehouseInfo, LocationInfo,
    ConfirmBoxRequest, ConfirmBoxResult
)
from app.services.reception_service import (
    get_packing_lists, get_boxes, get_box_detail,
    get_warehouses, get_locations, confirm_box,
    find_packing_by_barcode
)
from app.services.rfid_listener import RFIDListener
from app.settings import settings
from app.db.connection import db_cursor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Receção"])

@router.get("/warehouses", response_model=list[WarehouseInfo])
def list_warehouses():
    return get_warehouses()

@router.get("/warehouses/{wh_id}/locations", response_model=list[LocationInfo])
def list_locations(wh_id: int):
    return get_locations(wh_id)

@router.get("/packing", response_model=list[PackingListSummary])
def list_packings():
    return get_packing_lists()

@router.get("/packing/{order_id}/boxes", response_model=list[BoxSummary])
def list_boxes(order_id: int):
    return get_boxes(order_id)

@router.get("/packing/{order_id}/boxes/{vol_num}", response_model=BoxDetail)
def box_detail(order_id: int, vol_num: int):
    box = get_box_detail(vol_num)
    if not box:
        raise HTTPException(status_code=404, detail="Caixa não encontrada")
    return box

@router.post("/packing/{order_id}/boxes/{vol_num}/confirm", response_model=ConfirmBoxResult)
def confirm_box_endpoint(order_id: int, vol_num: int, req: ConfirmBoxRequest):
    result = confirm_box(vol_num, req)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result

# ── Singleton RFID ─────────────────────────────────────────────────────────────
_rfid_listener = None  # type: Optional[RFIDListener]
_rfid_task = None
_rfid_websockets: set = set()


async def _get_rfid_listener() -> RFIDListener:
    global _rfid_listener, _rfid_task

    async def broadcast(current_tags: set[str]):
        msg = json.dumps({"count": len(current_tags), "tags": list(current_tags)})
        dead = set()
        for ws in _rfid_websockets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        _rfid_websockets.difference_update(dead)

    if _rfid_listener is None or not _rfid_listener._running:
        # Determina antenas activas e potência a partir do .env
        active_antennas = [
            i for i in range(1, 5)
            if getattr(settings, f"RFID_ANTENNA{i}_ENABLED", 0) == 1
        ]
        if not active_antennas:
            active_antennas = [1]

        # Usa o valor TX_POWER do .env como índice sllurp (0=mín, 192=máx para Zebra FX7500)
        tx_index = getattr(settings, f"RFID_ANTENNA{active_antennas[0]}_TX_POWER", 192)

        logger.info(f"RFID: antenas activas={active_antennas} tx_index={tx_index}")

        _rfid_listener = RFIDListener(
            host      = settings.RFID_HOST,
            port      = settings.RFID_PORT,
            on_update = broadcast,
            antennas  = active_antennas,
            tx_power  = tx_index,
        )
        _rfid_task = asyncio.create_task(_rfid_listener.start())

    return _rfid_listener


@router.websocket("/ws/rfid")
async def rfid_websocket(websocket: WebSocket):
    await websocket.accept()
    _rfid_websockets.add(websocket)
    listener = await _get_rfid_listener()

    try:
        while True:
            msg  = await websocket.receive_text()
            data = json.loads(msg)
            action = data.get("action")
            if action == "reset":
                # Carrega blacklist da BD em executor (não bloqueia o event loop)
                confirmed: set[str] = set()
                try:
                    from app.db.connection import db_cursor as _dbc
                    def _load():
                        with _dbc() as (cur, _):
                            cur.execute("SELECT TAG FROM ItemMasterRFIDTags WHERE deleted=0 AND TAG IS NOT NULL")
                            return {r[0] for r in cur.fetchall()}
                    loop = asyncio.get_event_loop()
                    confirmed = await loop.run_in_executor(None, _load)
                    logger.info(f"Nova leitura — {len(confirmed)} tags confirmadas na blacklist")
                except Exception as e:
                    logger.warning(f"Erro ao carregar blacklist: {e}")

                listener.reset(confirmed_tags=confirmed)
                dead = set()
                for ws in _rfid_websockets:
                    try:
                        await ws.send_text(json.dumps({"count": 0, "tags": []}))
                    except Exception:
                        dead.add(ws)
                _rfid_websockets.difference_update(dead)
            elif action == "set_delay":
                listener.set_restart_delay(float(data.get("delay", 3.0)))
    except WebSocketDisconnect:
        pass
    finally:
        _rfid_websockets.discard(websocket)


@router.get("/packing/by-barcode/{barcode}")
def packing_by_barcode(barcode: str):
    row = find_packing_by_barcode(barcode)
    if not row:
        raise HTTPException(status_code=404, detail=f"Nenhum packing encontrado para a caixa '{barcode}'")

    order_id = row[1]
    escp_order_id = None
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TOP 1 OrderIDOri
            FROM ClientOrderDetailsOri
            WHERE DocType='PSCP' AND OrderID=? AND DocTypeOri='ESCP'
            ORDER BY OrderRowOri ASC
        """, (order_id,))
        escp_row = cursor.fetchone()
        if escp_row:
            escp_order_id = escp_row[0]

    return {
        "vol_num":       row[0],
        "order_id":      order_id,
        "client_id":     row[2],
        "delivery_date": str(row[3])[:10] if row[3] else None,
        "obs":           row[4] or '',
        "total_qty":     int(row[5] or 0),
        "escp_order_id": escp_order_id,
    }
