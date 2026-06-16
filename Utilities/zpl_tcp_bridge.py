#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import socketserver
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 9100
DEFAULT_TITLE = "S4toSCP ZPL Bridge"


@dataclass
class BridgeConfig:
    printer: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    title: str = DEFAULT_TITLE
    keep_files: bool = False


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ZplBridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        config: BridgeConfig = self.server.bridge_config  # type: ignore[attr-defined]
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        payload = bytearray()

        while True:
            chunk = self.request.recv(65536)
            if not chunk:
                break
            payload.extend(chunk)

        if not payload:
            print(f"[bridge] ligacao vazia de {client}", flush=True)
            return

        print(f"[bridge] recebido job de {client} com {len(payload)} bytes", flush=True)
        file_path = _write_temp_job(bytes(payload))
        try:
            _send_to_printer(file_path, config)
            print(f"[bridge] job enviado para '{config.printer}'", flush=True)
        except RuntimeError as exc:
            print(f"[bridge] erro ao imprimir para '{config.printer}': {exc}", flush=True)
        finally:
            if config.keep_files:
                print(f"[bridge] ficheiro preservado em {file_path}", flush=True)
            else:
                file_path.unlink(missing_ok=True)


def _write_temp_job(payload: bytes) -> Path:
    fd, path = tempfile.mkstemp(prefix="s4-zpl-", suffix=".zpl")
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
    return Path(path)


def _send_to_printer(file_path: Path, config: BridgeConfig) -> None:
    attempts = [
        ["lp", "-d", config.printer, "-t", config.title, "-o", "raw", str(file_path)],
        ["lpr", "-P", config.printer, "-l", str(file_path)],
    ]

    errors: list[str] = []
    for cmd in attempts:
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            if completed.stdout.strip():
                print(f"[bridge] {completed.stdout.strip()}", flush=True)
            if completed.stderr.strip():
                print(f"[bridge] {completed.stderr.strip()}", flush=True)
            return
        except FileNotFoundError:
            errors.append(f"{cmd[0]}: comando nao encontrado")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            detail = stderr or stdout or f"exit code {exc.returncode}"
            errors.append(f"{cmd[0]} falhou: {detail}")

    raise RuntimeError("; ".join(errors) or "nao foi possivel enviar para a impressora local")


def parse_args() -> BridgeConfig:
    parser = argparse.ArgumentParser(
        description="Aceita ZPL via TCP e envia para uma impressora local no macOS.",
    )
    parser.add_argument("--printer", required=True, help="Nome da impressora local no macOS")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host de escuta (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Porta TCP (default: {DEFAULT_PORT})")
    parser.add_argument("--title", default=DEFAULT_TITLE, help="Titulo do job de impressao")
    parser.add_argument("--keep-files", action="store_true", help="Mantem os ficheiros ZPL temporarios")
    args = parser.parse_args()
    return BridgeConfig(
        printer=args.printer,
        host=args.host,
        port=args.port,
        title=args.title,
        keep_files=bool(args.keep_files),
    )


def main() -> int:
    config = parse_args()
    try:
        with ThreadedTCPServer((config.host, config.port), ZplBridgeHandler) as server:
            server.bridge_config = config  # type: ignore[attr-defined]
            print(
                f"[bridge] a escuta em {config.host}:{config.port} -> impressora '{config.printer}'",
                flush=True,
            )
            server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bridge] terminado pelo utilizador", flush=True)
        return 0
    except OSError as exc:
        print(f"[bridge] erro ao iniciar: {exc}", file=sys.stderr, flush=True)
        return 1
    except RuntimeError as exc:
        print(f"[bridge] erro: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
