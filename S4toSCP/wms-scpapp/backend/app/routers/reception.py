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

# ── Túneis RFID ───────────────────────────────────────────────────────────────
# tunnel_id -> {"listener": RFIDListener, "task": Task, "wss": set}
_tunnels: dict = {}


def _load_tunnel_config(tunnel_id: int):
    """Lê configuração do túnel da BD. Sempre relê — nunca usa cache."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT RFID_Host, RFID_Port,
                   Antenna1_Enabled, Antenna2_Enabled, Antenna3_Enabled, Antenna4_Enabled
            FROM RFIDTunnels WHERE TunnelID=? AND Active=1
        """, (tunnel_id,))
        row = cursor.fetchone()

    if row:
        host     = row[0]
        port     = row[1]
        antennas = [i+1 for i in range(4) if row[2+i]]
        if not antennas:
            antennas = [2]  # fallback seguro — nunca antena 1 por defeito
    else:
        # Fallback para .env
        host     = settings.RFID_HOST
        port     = settings.RFID_PORT
        antennas = [i for i in range(1, 5)
                    if getattr(settings, f"RFID_ANTENNA{i}_ENABLED", 0) == 1] or [2]

    return host, port, antennas


async def _get_tunnel_listener(tunnel_id: int):
    """Obtém ou cria listener para o túnel. Relê config da BD sempre que cria novo."""
    if tunnel_id not in _tunnels or not _tunnels[tunnel_id]["listener"]._running:
        host, port, antennas = _load_tunnel_config(tunnel_id)

        wss: set = set()

        async def broadcast(current_tags: set):
            msg = json.dumps({"type": "tags", "count": len(current_tags), "tags": list(current_tags)})
            dead = set()
            for ws in wss:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            wss.difference_update(dead)

        listener = RFIDListener(host=host, port=port, on_update=broadcast, antennas=antennas)
        task     = asyncio.create_task(listener.start())
        logger.info(f"Túnel {tunnel_id}: {host}:{port} antenas={antennas}")
        _tunnels[tunnel_id] = {"listener": listener, "task": task, "wss": wss}

    return _tunnels[tunnel_id]["listener"], _tunnels[tunnel_id]["wss"]


@router.websocket("/ws/rfid")
async def rfid_websocket(websocket: WebSocket, tunnel_id: int = 1):
    await websocket.accept()
    listener, wss = await _get_tunnel_listener(tunnel_id)
    wss.add(websocket)

    # Envia estado inicial — frontend sabe que está pronto
    await websocket.send_text(json.dumps({
        "type":  "ready",
        "count": len(listener.get_tags()),
        "tags":  list(listener.get_tags()),
    }))

    try:
        while True:
            msg    = await websocket.receive_text()
            data   = json.loads(msg)
            action = data.get("action")

            if action in ("start", "reset"):
                # "start" = operador carregou Nova Leitura
                # "reset" = mesma acção, nome alternativo
                await listener.reset()
                # Notifica todos os WebSockets do mesmo túnel
                dead = set()
                for ws in wss:
                    try:
                        await ws.send_text(json.dumps({"type": "reset", "count": 0, "tags": []}))
                    except Exception:
                        dead.add(ws)
                wss.difference_update(dead)

            elif action == "stop":
                # Operador validou caixa — para leitura activa
                await listener.stop()
                # Recria listener para o próximo ciclo
                del _tunnels[tunnel_id]

            elif action == "set_delay":
                listener.set_restart_delay(float(data.get("delay", 3.0)))

    except WebSocketDisconnect:
        pass
    finally:
        wss.discard(websocket)


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
