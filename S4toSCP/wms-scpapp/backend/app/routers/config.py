from __future__ import annotations
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.settings import settings
import os, re

router = APIRouter(prefix="/config", tags=["Configuração"])

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")


class AntennaConfig(BaseModel):
    antenna: int        # 1-4
    enabled: bool
    tx_power: int       # dBm x 100
    rx_sensitivity: int


class RFIDConfig(BaseModel):
    host: str
    port: int
    antennas: list[AntennaConfig]


class TunnelAntennaConfig(BaseModel):
    antenna: int
    enabled: bool
    tx_power: int
    rx_sensitivity: int = 0


class TunnelRFIDConfig(BaseModel):
    tunnel_id: int
    host: str
    port: int
    antennas: list[TunnelAntennaConfig]
    active: bool = True


def _read_env() -> dict:
    """Lê o .env como dicionário."""
    env = {}
    try:
        with open(ENV_PATH, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def _write_env(updates: dict):
    """Atualiza valores no .env preservando comentários e ordem."""
    try:
        with open(ENV_PATH, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            k = stripped.split('=', 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated_keys.add(k)
                continue
        new_lines.append(line)

    # Adiciona chaves novas que não existiam
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")

    with open(ENV_PATH, 'w') as f:
        f.writelines(new_lines)


@router.get("/rfid", response_model=RFIDConfig)
def get_rfid_config():
    """Devolve configuração atual do RFID."""
    return RFIDConfig(
        host = settings.RFID_HOST,
        port = settings.RFID_PORT,
        antennas = [
            AntennaConfig(
                antenna        = i,
                enabled        = bool(getattr(settings, f'RFID_ANTENNA{i}_ENABLED')),
                tx_power       = getattr(settings, f'RFID_ANTENNA{i}_TX_POWER'),
                rx_sensitivity = getattr(settings, f'RFID_ANTENNA{i}_RX_SENSITIVITY'),
            )
            for i in range(1, 5)
        ]
    )


@router.post("/rfid", response_model=RFIDConfig)
def save_rfid_config(cfg: RFIDConfig):
    """Guarda configuração RFID no .env."""
    updates = {
        'RFID_HOST': cfg.host,
        'RFID_PORT': str(cfg.port),
    }
    for ant in cfg.antennas:
        i = ant.antenna
        updates[f'RFID_ANTENNA{i}_ENABLED']       = '1' if ant.enabled else '0'
        updates[f'RFID_ANTENNA{i}_TX_POWER']       = str(ant.tx_power)
        updates[f'RFID_ANTENNA{i}_RX_SENSITIVITY'] = str(ant.rx_sensitivity)

    _write_env(updates)
    return cfg


# ── Túneis RFID ────────────────────────────────────────────────────────────────
from app.db.connection import db_cursor as _db_cursor

@router.get("/tunnels")
def list_tunnels():
    with _db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TunnelID, TunnelCode, TunnelDesc, RFID_Host, RFID_Port,
                   Antenna1_Enabled, Antenna2_Enabled, Antenna3_Enabled, Antenna4_Enabled,
                   Antenna1_TxPower, Antenna2_TxPower, Antenna3_TxPower, Antenna4_TxPower,
                   Active
            FROM RFIDTunnels WHERE Active=1 ORDER BY TunnelID
        """)
        rows = cursor.fetchall()
    return [{
        "tunnel_id":   r[0], "tunnel_code": r[1], "tunnel_desc": r[2],
        "host": r[3], "port": r[4],
        "antennas": [i+1 for i in range(4) if r[5+i]],
        "tx_powers": [r[9], r[10], r[11], r[12]],
        "rx_sensitivity": [0, 0, 0, 0],
        "active": bool(r[13]),
    } for r in rows]


@router.get("/tunnels/{tunnel_id}/rfid", response_model=TunnelRFIDConfig)
def get_tunnel_rfid_config(tunnel_id: int):
    with _db_cursor() as (cursor, _):
        cursor.execute("""
            SELECT TunnelID, RFID_Host, RFID_Port,
                   Antenna1_Enabled, Antenna2_Enabled, Antenna3_Enabled, Antenna4_Enabled,
                   Antenna1_TxPower, Antenna2_TxPower, Antenna3_TxPower, Antenna4_TxPower,
                   Active
            FROM RFIDTunnels
            WHERE TunnelID=?
        """, (tunnel_id,))
        row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"Túnel RFID {tunnel_id} não encontrado")

    antennas = [
        TunnelAntennaConfig(
            antenna=i + 1,
            enabled=bool(row[3 + i]),
            tx_power=int(row[7 + i] or 0),
            rx_sensitivity=0,
        )
        for i in range(4)
    ]
    return TunnelRFIDConfig(
        tunnel_id=row[0],
        host=row[1],
        port=int(row[2]),
        antennas=antennas,
        active=bool(row[11]),
    )


@router.put("/tunnels/{tunnel_id}/rfid", response_model=TunnelRFIDConfig)
def save_tunnel_rfid_config(tunnel_id: int, cfg: TunnelRFIDConfig):
    if cfg.tunnel_id != tunnel_id:
        raise HTTPException(status_code=400, detail="O tunnel_id do path e do body têm de coincidir")

    antennas = {antenna.antenna: antenna for antenna in cfg.antennas}
    missing = [str(antenna) for antenna in range(1, 5) if antenna not in antennas]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Faltam configurações para as antenas: {', '.join(missing)}",
        )

    with _db_cursor() as (cursor, conn):
        cursor.execute("SELECT 1 FROM RFIDTunnels WHERE TunnelID=?", (tunnel_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"Túnel RFID {tunnel_id} não encontrado")

        cursor.execute("""
            UPDATE RFIDTunnels
            SET RFID_Host=?,
                RFID_Port=?,
                Antenna1_Enabled=?, Antenna2_Enabled=?, Antenna3_Enabled=?, Antenna4_Enabled=?,
                Antenna1_TxPower=?, Antenna2_TxPower=?, Antenna3_TxPower=?, Antenna4_TxPower=?,
                Active=?
            WHERE TunnelID=?
        """, (
            cfg.host,
            cfg.port,
            1 if antennas[1].enabled else 0,
            1 if antennas[2].enabled else 0,
            1 if antennas[3].enabled else 0,
            1 if antennas[4].enabled else 0,
            antennas[1].tx_power,
            antennas[2].tx_power,
            antennas[3].tx_power,
            antennas[4].tx_power,
            1 if cfg.active else 0,
            tunnel_id,
        ))
        conn.commit()

    return get_tunnel_rfid_config(tunnel_id)
