from __future__ import annotations
import asyncio
import re
import sys
import logging
from typing import Callable

logger = logging.getLogger(__name__)

EPC_RE = re.compile(r"'EPC(?:-96)?':\s*b'([0-9A-Fa-f]+)'")


class RFIDListener:
    """
    Lança um processo sllurp por antena activa em paralelo.
    Todas as antenas lêem em simultâneo — sem -X para usar potência máxima do leitor.
    """

    def __init__(self, host: str, port: int, on_update: Callable,
                 antennas: list = None, tx_power: int = 0):
        self.host      = host
        self.port      = port
        self.on_update = on_update
        self.antennas  = antennas or [2, 3, 4]
        self._tags:      set = set()
        self._confirmed: set = set()
        self._running    = False
        self._procs:     list = []
        self._restart_delay = 3.0
        self._lock       = asyncio.Lock()

    async def start(self):
        self._running = True
        while self._running:
            try:
                await self._run_all_antennas()
            except Exception as e:
                logger.warning(f"RFID erro: {e}")
            if self._running:
                logger.info("RFID: a reiniciar...")
                await asyncio.sleep(self._restart_delay)

    async def _run_all_antennas(self):
        logger.info(f"RFID: {self.host} antenas={self.antennas}")
        tasks = []
        for antenna in self.antennas:
            cmd = [
                sys.executable, "-m", "sllurp", "inventory",
                "-a", str(antenna),
                "-n", "1",
                self.host,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._procs.append(proc)
            tasks.append(asyncio.create_task(self._read_proc(proc, antenna)))

        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
        finally:
            await self._stop_all_procs()

    async def _read_proc(self, proc, antenna: int):
        try:
            async for raw in proc.stdout:
                if not self._running:
                    break
                line = raw.decode(errors='ignore').strip()
                if line:
                    logger.debug(f"A{antenna}: {line}")
                matches = EPC_RE.findall(line)
                if matches:
                    async with self._lock:
                        new_found = []
                        for epc in matches:
                            epc = epc.upper()
                            if epc not in self._tags and epc not in self._confirmed:
                                self._tags.add(epc)
                                new_found.append(epc)
                    if new_found:
                        logger.info(f"A{antenna} +{len(new_found)} tags | total={len(self._tags)}")
                        await self.on_update(set(self._tags))
        except Exception as e:
            logger.warning(f"A{antenna} erro: {e}")

    async def _stop_all_procs(self):
        for proc in list(self._procs):
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        self._procs.clear()

    async def stop(self):
        self._running = False
        await self._stop_all_procs()

    async def reset(self):
        async with self._lock:
            self._tags.clear()
        await self._stop_all_procs()
        logger.info("RFID: reset OK")

    def add_confirmed(self, tags: list):
        self._confirmed.update(t.upper() for t in tags)

    def get_tags(self) -> set:
        return set(self._tags)

    def set_restart_delay(self, delay: float):
        self._restart_delay = delay
