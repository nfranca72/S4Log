from __future__ import annotations

import argparse
import json
import socket
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PORT = 9100


@dataclass
class ProbeResult:
    printer_ip: str
    printer_port: int
    mode: str
    copies_printed: int
    timestamp_utc: str
    device_unique_id: str
    rfid_log_enabled: str
    rfid_error_response: str
    last_result_line1: str
    last_result_line2: str
    rfid_log_entries: str
    host_response: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Valida se a Zebra ZT411R expõe EPCs/entradas RFID após um lote de impressão."
    )
    parser.add_argument("--ip", required=True, help="IP da impressora Zebra")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Porta TCP da impressora")
    parser.add_argument("--copies", type=int, default=2, help="Número de etiquetas de teste a imprimir")
    parser.add_argument(
        "--mode",
        choices=("passive-log", "explicit-rfid-read"),
        default="passive-log",
        help="Modo do teste: simples ou leitura RFID explícita devolvida ao host",
    )
    parser.add_argument(
        "--wait-after-print",
        type=float,
        default=1.0,
        help="Segundos de espera após enviar o lote antes de recolher o log RFID",
    )
    parser.add_argument(
        "--output",
        default="data/zt411_rfid_batch_probe.json",
        help="Caminho do ficheiro JSON com o resultado",
    )
    return parser.parse_args()


def _send_command(sock: socket.socket, command: str) -> None:
    sock.sendall(command.encode("utf-8"))


def _recv_response(sock: socket.socket, timeout: float = 1.0) -> str:
    chunks: list[bytes] = []
    previous_timeout = sock.gettimeout()
    try:
        sock.settimeout(timeout)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
    except socket.timeout:
        pass
    finally:
        sock.settimeout(previous_timeout)
    return b"".join(chunks).decode("utf-8", errors="ignore").strip()


def _getvar(sock: socket.socket, name: str) -> str:
    _send_command(sock, f'! U1 getvar "{name}"\n')
    return _recv_response(sock)


def _do(sock: socket.socket, name: str) -> str:
    _send_command(sock, f'! U1 do "{name}" ""\n')
    return _recv_response(sock)


def _build_probe_zpl(copies: int) -> str:
    labels: list[str] = []
    for index in range(1, copies + 1):
        labels.append(
            "\n".join(
                [
                    "^XA",
                    "^CI28",
                    "^PW600",
                    "^LL300",
                    "^FO40,40^A0N,38,38^FDRFID BATCH PROBE^FS",
                    f"^FO40,95^A0N,32,32^FDLABEL {index}/{copies}^FS",
                    "^FO40,145^A0N,26,26^FDS4-Log ZT411R batch validation^FS",
                    "^FO40,195^GB500,3,3^FS",
                    f"^FO40,220^A0N,22,22^FD{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}^FS",
                    "^XZ",
                ]
            )
        )
    return "\n".join(labels)


def _build_explicit_rfid_read_zpl(copies: int) -> str:
    labels: list[str] = []
    for index in range(1, copies + 1):
        labels.append(
            "\n".join(
                [
                    "^XA",
                    "^CI28",
                    "^PW600",
                    "^LL300",
                    "^FO40,40^A0N,38,38^FDRFID HOST READ PROBE^FS",
                    f"^FO40,95^A0N,32,32^FDLABEL {index}/{copies}^FS",
                    "^FO40,145^A0N,26,26^FD^RFR,H,0,12,1 + ^HV probe^FS",
                    "^FO40,195^GB500,3,3^FS",
                    "^FO40,220^A0N,22,22^FDEPC to host expected after print^FS",
                    "^RFR,H,0,12,1^FN1^FS",
                    "^HV1,,EPC:^FS",
                    "^XZ",
                ]
            )
        )
    return "\n".join(labels)


def _normalize_log_value(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _probe(ip: str, port: int, copies: int, wait_after_print: float, mode: str) -> ProbeResult:
    with socket.create_connection((ip, port), timeout=5.0) as sock:
        sock.settimeout(1.0)

        _do(sock, "rfid.log.clear")
        if mode == "explicit-rfid-read":
            payload = _build_explicit_rfid_read_zpl(copies)
        else:
            payload = _build_probe_zpl(copies)
        sock.sendall(payload.encode("utf-8"))
        time.sleep(wait_after_print)
        host_response = _recv_response(sock, timeout=1.5)

        return ProbeResult(
            printer_ip=ip,
            printer_port=port,
            mode=mode,
            copies_printed=copies,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            device_unique_id=_normalize_log_value(_getvar(sock, "device.unique_id")),
            rfid_log_enabled=_normalize_log_value(_getvar(sock, "rfid.log.enabled")),
            rfid_error_response=_normalize_log_value(_getvar(sock, "rfid.error.response")),
            last_result_line1=_normalize_log_value(_getvar(sock, "rfid.tag.read.result_line1")),
            last_result_line2=_normalize_log_value(_getvar(sock, "rfid.tag.read.result_line2")),
            rfid_log_entries=_normalize_log_value(_getvar(sock, "rfid.log.entries")),
            host_response=_normalize_log_value(host_response),
        )


def main() -> int:
    args = _parse_args()
    result = _probe(
        args.ip,
        args.port,
        max(args.copies, 0),
        max(args.wait_after_print, 0.0),
        args.mode,
    )

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(result), ensure_ascii=True, indent=2), encoding="utf-8")

    print(json.dumps(asdict(result), ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
