from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request


class RfidBridgeError(RuntimeError):
    """Raised when the RFID bridge request fails."""


@dataclass
class TunnelRfidConfig:
    host: str
    port: int
    antennas: list[int]
    tx_powers: dict[int, int]
    rx_sensitivity: dict[int, int]


class RfidBridgeClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_tags(self) -> dict[str, Any]:
        return self._request_json("GET", "/rfid/tags")

    def start(self, config: TunnelRfidConfig) -> dict[str, Any]:
        return self._request_json("POST", "/rfid/start", self._payload(config))

    def reset(self, config: TunnelRfidConfig) -> dict[str, Any]:
        return self._request_json("POST", "/rfid/reset", self._payload(config))

    def stop(self) -> dict[str, Any]:
        return self._request_json("POST", "/rfid/stop")

    def _payload(self, config: TunnelRfidConfig) -> dict[str, Any]:
        return {
            "host": config.host,
            "port": config.port,
            "antennas": config.antennas,
            "txPowers": {str(key): value for key, value in config.tx_powers.items()},
            "rxSensitivity": {str(key): value for key, value in config.rx_sensitivity.items()},
        }

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(
            url=f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RfidBridgeError(
                f"RFID bridge request failed ({exc.code}) for {path}: {body}"
            ) from exc
        except Exception as exc:
            raise RfidBridgeError(f"RFID bridge request failed for {path}: {exc}") from exc

        if not body:
            return {}
        return json.loads(body)
