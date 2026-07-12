from __future__ import annotations
import asyncio
import json
import logging
import os
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from app.models.schemas import (
    PackingListSummary, BoxSummary, BoxDetail,
    WarehouseInfo, LocationInfo,
    ConfirmBoxRequest, ConfirmBoxResult, CancelBoxConfirmationResult, CountingSnapshot
)
from app.services.reception_service import (
    get_packing_lists, get_boxes, get_box_detail,
    get_warehouses, get_locations, confirm_box,
    find_packing_by_barcode, cancel_box_confirmation, summarize_counting_tags
)
from app.services.rfid_bridge_client import (
    RfidBridgeClient,
    RfidBridgeError,
    TunnelRfidConfig,
)
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
def confirm_box_endpoint(order_id: int, vol_num: int, req: ConfirmBoxRequest, request: Request):
    result = confirm_box(
        vol_num,
        req,
        station_identifier=str(request.headers.get("X-Station-Identifier") or "").strip(),
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result


@router.post("/packing/{order_id}/boxes/{vol_num}/cancel-confirmation", response_model=CancelBoxConfirmationResult)
def cancel_box_confirmation_endpoint(order_id: int, vol_num: int):
    result = cancel_box_confirmation(vol_num, order_id)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)
    return result

_bridge_clients: dict[str, RfidBridgeClient] = {}


def _bridge_url_for_tunnel(tunnel_id: int) -> str:
    key = f"RFID_BRIDGE_TUNNEL_{tunnel_id}_URL"
    configured_url = os.getenv(key) or getattr(settings, key, None)
    return (configured_url or settings.RFID_BRIDGE_URL).rstrip("/")


def _bridge_client_for_tunnel(tunnel_id: int) -> RfidBridgeClient:
    bridge_url = _bridge_url_for_tunnel(tunnel_id)
    client = _bridge_clients.get(bridge_url)
    if client is None:
        client = RfidBridgeClient(bridge_url)
        _bridge_clients[bridge_url] = client
    return client

# ── Túneis RFID ───────────────────────────────────────────────────────────────
# tunnel_id -> {"wss": set, "poller": Task | None, "last_tags": set[str]}
_tunnels: dict[int, dict] = {}


def _filter_registered_rfid_tags(tags: set[str]) -> set[str]:
    if not tags:
        return set()

    tag_list = sorted(tags)
    placeholders = ",".join("?" for _ in tag_list)
    with db_cursor() as (cursor, _):
        cursor.execute(
            f"SELECT TAG FROM ItemMasterRFIDTags WHERE TAG IN ({placeholders})",
            tag_list,
        )
        registered = {str(row[0]).strip() for row in cursor.fetchall() if row[0]}

    return tags - registered


def _load_tunnel_config(tunnel_id: int):
    """Lê configuração do túnel da BD. Sempre relê — nunca usa cache."""
    with db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT RFID_Host, RFID_Port,
                   Antenna1_Enabled, Antenna2_Enabled, Antenna3_Enabled, Antenna4_Enabled,
                   Antenna1_TxPower, Antenna2_TxPower, Antenna3_TxPower, Antenna4_TxPower
            FROM RFIDTunnels WHERE TunnelID=? AND Active=1
        """, (tunnel_id,))
        row = cursor.fetchone()

    if row:
        host     = row[0]
        port     = row[1]
        antennas = [i+1 for i in range(4) if row[2+i]]
        tx_power = {i + 1: int(row[6 + i] or 0) for i in range(4)}
        rx_sensitivity = {
            i: getattr(settings, f"RFID_ANTENNA{i}_RX_SENSITIVITY", 0)
            for i in range(1, 5)
        }
        if not antennas:
            antennas = [2]  # fallback seguro — nunca antena 1 por defeito
    else:
        # Fallback para .env
        host     = settings.RFID_HOST
        port     = settings.RFID_PORT
        antennas = [i for i in range(1, 5)
                    if getattr(settings, f"RFID_ANTENNA{i}_ENABLED", 0) == 1] or [2]
        tx_power = {i: getattr(settings, f"RFID_ANTENNA{i}_TX_POWER", 0) for i in range(1, 5)}
        rx_sensitivity = {
            i: getattr(settings, f"RFID_ANTENNA{i}_RX_SENSITIVITY", 0)
            for i in range(1, 5)
        }

    return host, port, antennas, tx_power, rx_sensitivity


def _build_bridge_config(tunnel_id: int) -> TunnelRfidConfig:
    host, port, antennas, tx_power, rx_sensitivity = _load_tunnel_config(tunnel_id)
    return TunnelRfidConfig(
        host=host,
        port=port,
        antennas=antennas,
        tx_powers={ant: int(tx_power.get(ant, 0) or 0) for ant in antennas},
        rx_sensitivity={ant: int(rx_sensitivity.get(ant, 0) or 0) for ant in antennas},
    )


def _extract_bridge_tags(snapshot: dict) -> set[str]:
    return {
        str(tag.get("epc", "")).strip()
        for tag in snapshot.get("tags", [])
        if str(tag.get("epc", "")).strip()
    }


async def _broadcast_tunnel_tags(tunnel_id: int, tags: set[str], event_type: str = "tags"):
    tunnel = _tunnels.get(tunnel_id)
    if not tunnel:
        return

    msg = json.dumps({"type": event_type, "count": len(tags), "tags": sorted(tags)})
    dead = set()
    for ws in tunnel["wss"]:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    tunnel["wss"].difference_update(dead)


async def _poll_bridge_tags(tunnel_id: int):
    try:
        while True:
            tunnel = _tunnels.get(tunnel_id)
            if not tunnel or not tunnel["wss"]:
                return

            bridge_client = _bridge_client_for_tunnel(tunnel_id)
            snapshot = await asyncio.to_thread(bridge_client.get_tags)
            tags = _extract_bridge_tags(snapshot)
            tags = _filter_registered_rfid_tags(tags)
            if tags != tunnel["last_tags"]:
                tunnel["last_tags"] = tags
                await _broadcast_tunnel_tags(tunnel_id, tags)

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Erro a fazer polling RFID bridge para o túnel %s", tunnel_id)


def _ensure_tunnel_state(tunnel_id: int) -> dict:
    tunnel = _tunnels.get(tunnel_id)
    if tunnel is None:
        tunnel = {"wss": set(), "poller": None, "last_tags": set()}
        _tunnels[tunnel_id] = tunnel
    return tunnel


async def _ensure_tunnel_poller(tunnel_id: int):
    tunnel = _ensure_tunnel_state(tunnel_id)
    poller = tunnel.get("poller")
    if poller is None or poller.done():
        tunnel["poller"] = asyncio.create_task(_poll_bridge_tags(tunnel_id))


@router.websocket("/ws/rfid")
async def rfid_websocket(websocket: WebSocket, tunnel_id: int = 1):
    await websocket.accept()
    tunnel = _ensure_tunnel_state(tunnel_id)
    tunnel["wss"].add(websocket)

    try:
        bridge_client = _bridge_client_for_tunnel(tunnel_id)
        snapshot = await asyncio.to_thread(bridge_client.get_tags)
    except RfidBridgeError as exc:
        tunnel["wss"].discard(websocket)
        await websocket.close(code=1011, reason=str(exc)[:120])
        return

    tags = _extract_bridge_tags(snapshot)
    tags = _filter_registered_rfid_tags(tags)
    tunnel["last_tags"] = tags
    await _ensure_tunnel_poller(tunnel_id)
    await websocket.send_text(json.dumps({
        "type": "ready",
        "count": len(tags),
        "tags": sorted(tags),
    }))

    try:
        while True:
            msg    = await websocket.receive_text()
            data   = json.loads(msg)
            action = data.get("action")

            if action in ("start", "reset"):
                config = _build_bridge_config(tunnel_id)
                logger.info(
                    "Túnel %s: bridge RFID %s:%s antenas=%s tx=%s rx=%s",
                    tunnel_id,
                    config.host,
                    config.port,
                    config.antennas,
                    config.tx_powers,
                    config.rx_sensitivity,
                )
                bridge_client = _bridge_client_for_tunnel(tunnel_id)
                if action == "start":
                    await asyncio.to_thread(bridge_client.start, config)
                else:
                    await asyncio.to_thread(bridge_client.reset, config)
                tunnel["last_tags"] = set()
                await _ensure_tunnel_poller(tunnel_id)
                await _broadcast_tunnel_tags(tunnel_id, set(), "reset")

            elif action == "stop":
                bridge_client = _bridge_client_for_tunnel(tunnel_id)
                await asyncio.to_thread(bridge_client.stop)
            elif action == "set_delay":
                logger.info("RFID bridge ignora set_delay para o túnel %s", tunnel_id)

    except WebSocketDisconnect:
        pass
    except RfidBridgeError as exc:
        logger.exception("Erro RFID bridge no túnel %s", tunnel_id)
        await websocket.send_text(json.dumps({"type": "error", "detail": str(exc)}))
    finally:
        tunnel["wss"].discard(websocket)
        if not tunnel["wss"] and tunnel_id in _tunnels:
            poller = tunnel.get("poller")
            if poller and not poller.done():
                poller.cancel()
                try:
                    await poller
                except asyncio.CancelledError:
                    pass
            _tunnels.pop(tunnel_id, None)


@router.post("/counting/tunnels/{tunnel_id}/start")
async def start_counting_tunnel(tunnel_id: int):
    config = _build_bridge_config(tunnel_id)
    bridge_client = _bridge_client_for_tunnel(tunnel_id)
    await asyncio.to_thread(bridge_client.start, config)
    return {"success": True}


@router.post("/counting/tunnels/{tunnel_id}/reset")
async def reset_counting_tunnel(tunnel_id: int):
    config = _build_bridge_config(tunnel_id)
    bridge_client = _bridge_client_for_tunnel(tunnel_id)
    await asyncio.to_thread(bridge_client.reset, config)
    return {"success": True}


@router.post("/counting/tunnels/{tunnel_id}/stop")
async def stop_counting_tunnel(tunnel_id: int):
    bridge_client = _bridge_client_for_tunnel(tunnel_id)
    await asyncio.to_thread(bridge_client.stop)
    return {"success": True}


@router.get("/counting/tunnels/{tunnel_id}/snapshot", response_model=CountingSnapshot)
async def counting_tunnel_snapshot(tunnel_id: int):
    bridge_client = _bridge_client_for_tunnel(tunnel_id)
    snapshot = await asyncio.to_thread(bridge_client.get_tags)
    return summarize_counting_tags(sorted(_extract_bridge_tags(snapshot)), tunnel_id=tunnel_id)


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
