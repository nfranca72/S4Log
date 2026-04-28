from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sllurp.llrp import LLRPReaderClient, LLRPReaderConfig, LLRPReaderState

logger = logging.getLogger(__name__)


class RFIDListener:
    """
    Mantém uma sessão LLRP persistente com o leitor Zebra.
    A ligação ao leitor permanece aberta; o inventário é que é iniciado/parado
    por ciclo de leitura.
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_update: Callable,
        antennas: list[int] | None = None,
        tx_power: dict[int, int] | int | None = None,
        rx_sensitivity: dict[int, int] | None = None,
    ):
        self.host = host
        self.port = port
        self.on_update = on_update
        self.antennas = antennas or [2]
        self.tx_power = tx_power or {ant: 0 for ant in self.antennas}
        self.rx_sensitivity = rx_sensitivity or {}

        self._tags: set[str] = set()
        self._confirmed: set[str] = set()
        self._running = False
        self._inventory_active = False
        self._restart_delay = 3.0
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader: LLRPReaderClient | None = None
        self._reader_closed: asyncio.Event | None = None
        self._connected: asyncio.Event | None = None
        self._pending_start = False

    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._running = True

        if any(self.rx_sensitivity.get(ant, 0) for ant in self.antennas):
            logger.warning(
                "RFID: rx_sensitivity configurada mas ainda nao aplicada via sllurp API publica"
            )

        while self._running:
            self._reader_closed = asyncio.Event()
            self._connected = asyncio.Event()
            try:
                await self._connect_reader()
                await self._reader_closed.wait()
            except Exception as exc:
                logger.warning("RFID erro: %s", exc)
            finally:
                self._inventory_active = False
                self._reader = None
                self._connected = None
                self._reader_closed = None

            if self._running:
                logger.info("RFID: a reiniciar sessao LLRP em %.1fs", self._restart_delay)
                await asyncio.sleep(self._restart_delay)

    async def _connect_reader(self):
        tx_power_dbm, tx_power_index = self._normalize_tx_power()

        config = LLRPReaderConfig(
            {
                "start_inventory": False,
                "reset_on_connect": True,
                "disconnect_when_done": False,
                "reconnect": False,
                "antennas": self.antennas,
                "report_every_n_tags": 1,
                "tag_content_selector": {
                    "EnableROSpecID": False,
                    "EnableSpecIndex": False,
                    "EnableInventoryParameterSpecID": False,
                    "EnableAntennaID": True,
                    "EnableChannelIndex": True,
                    "EnablePeakRSSI": True,
                    "EnableFirstSeenTimestamp": False,
                    "EnableLastSeenTimestamp": True,
                    "EnableTagSeenCount": True,
                    "EnableAccessSpecID": False,
                    "C1G2EPCMemorySelector": {
                        "EnableCRC": False,
                        "EnablePCBits": False,
                    },
                },
            }
        )
        if tx_power_dbm is not None:
            config.tx_power_dbm = tx_power_dbm
        else:
            config.tx_power = tx_power_index

        reader = LLRPReaderClient(self.host, self.port, config)
        reader.add_tag_report_callback(self._handle_tag_report)
        reader.add_state_callback(LLRPReaderState.STATE_CONNECTED, self._handle_connected)
        reader.add_state_callback(LLRPReaderState.STATE_INVENTORYING, self._handle_inventorying)
        reader.add_disconnected_callback(self._handle_disconnected)
        reader.connect()

        self._reader = reader
        logger.info(
            "RFID: sessao LLRP aberta para %s:%s antenas=%s tx=%s",
            self.host,
            self.port,
            self.antennas,
            tx_power_dbm if tx_power_dbm is not None else tx_power_index,
        )

    def _normalize_tx_power(self) -> tuple[dict[int, float] | None, dict[int, int] | int]:
        tx_power = self.tx_power
        if isinstance(tx_power, int):
            tx_power = {ant: tx_power for ant in self.antennas}

        tx_power_map = {ant: int(tx_power.get(ant, 0)) for ant in self.antennas}
        if any(value > 100 for value in tx_power_map.values()):
            # Alguns leitores rejeitam ROSpec quando recebem potência em dBm
            # convertida diretamente; neste caso usamos o máximo suportado.
            return (None, {ant: 0 for ant in self.antennas})

        if any(value > 0 for value in tx_power_map.values()):
            return (None, tx_power_map)

        return (None, {ant: 0 for ant in self.antennas})

    def _handle_connected(self, _reader: LLRPReaderClient, _state: int):
        if self._loop and self._connected:
            self._loop.call_soon_threadsafe(self._connected.set)
        if self._pending_start:
            self._start_inventory()

    def _handle_inventorying(self, _reader: LLRPReaderClient, _state: int):
        self._inventory_active = True

    def _handle_disconnected(self, _reader: LLRPReaderClient):
        self._inventory_active = False
        if self._loop and self._reader_closed:
            self._loop.call_soon_threadsafe(self._reader_closed.set)

    def _handle_tag_report(self, _reader: LLRPReaderClient, tags: list[dict[str, Any]]):
        if not self._loop:
            return
        self._loop.call_soon_threadsafe(
            asyncio.create_task,
            self._process_tag_report(tags),
        )

    async def _process_tag_report(self, tags: list[dict[str, Any]]):
        new_found: list[str] = []
        async with self._lock:
            for tag in tags:
                epc = self._extract_epc(tag)
                if not epc:
                    continue
                if epc not in self._tags and epc not in self._confirmed:
                    self._tags.add(epc)
                    new_found.append(epc)

        if new_found:
            logger.info("RFID +%d tags | total=%d", len(new_found), len(self._tags))
            await self.on_update(set(self._tags))

    @staticmethod
    def _extract_epc(tag: dict[str, Any]) -> str | None:
        epc = tag.get("EPC") or tag.get("EPC-96")
        if isinstance(epc, bytes):
            return epc.hex().upper()
        if isinstance(epc, str):
            return epc.upper()
        return None

    async def _wait_until_connected(self, timeout: float = 5.0):
        if self._connected and not self._connected.is_set():
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    def _start_inventory(self, force_regen_rospec: bool = False):
        if not self._reader:
            return
        try:
            self._reader.llrp.startInventory(force_regen_rospec=force_regen_rospec)
            self._inventory_active = True
            self._pending_start = False
            logger.info("RFID: inventario iniciado")
        except Exception as exc:
            logger.warning("RFID: erro ao iniciar inventario: %s", exc)

    async def _stop_inventory(self):
        if not self._reader:
            return
        if self._reader.llrp.state != LLRPReaderState.STATE_INVENTORYING:
            self._inventory_active = False
            return

        if not self._loop:
            return

        stopped = self._loop.create_future()

        def on_stopped(state, is_success, *args):
            self._inventory_active = False
            if not stopped.done():
                self._loop.call_soon_threadsafe(stopped.set_result, bool(is_success))
            if is_success:
                self._reader.llrp.setState(LLRPReaderState.STATE_CONNECTED)

        self._reader.llrp.stopPolitely(onCompletion=on_stopped)
        await asyncio.wait_for(stopped, timeout=10)
        logger.info("RFID: inventario parado")

    async def stop(self):
        await self._stop_inventory()

    async def reset(self):
        async with self._lock:
            self._tags.clear()

        await self._wait_until_connected()

        if self._reader and self._reader.llrp.state == LLRPReaderState.STATE_INVENTORYING:
            await self._stop_inventory()

        if self._reader:
            self._pending_start = False
            self._start_inventory()
        else:
            self._pending_start = True
        logger.info("RFID: reset OK")

    async def close(self):
        self._running = False
        self._pending_start = False

        reader = self._reader
        if not reader:
            if self._reader_closed:
                self._reader_closed.set()
            return

        try:
            await asyncio.to_thread(reader.disconnect, 5)
        except Exception as exc:
            logger.warning("RFID: erro ao fechar sessao: %s", exc)
            try:
                reader.hard_disconnect()
            except Exception:
                pass
        finally:
            self._inventory_active = False
            if self._reader_closed:
                self._reader_closed.set()

    def add_confirmed(self, tags: list[str]):
        self._confirmed.update(t.upper() for t in tags)

    def get_tags(self) -> set[str]:
        return set(self._tags)

    def set_restart_delay(self, delay: float):
        self._restart_delay = delay
