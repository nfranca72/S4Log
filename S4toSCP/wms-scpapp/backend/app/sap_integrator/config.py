"""
config.py — Central configuration loaded from .env
All settings are persisted; toggles and series can be updated at runtime
and written back to the .env file so they survive restarts.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"
DEFAULT_SQLITE_DB = BACKEND_ROOT / "data" / "sap_integrator.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SAP Service Layer
    sap_sl_host: str = "https://localhost:50000"
    sap_sl_company: str = ""
    sap_sl_user: str = ""
    sap_sl_password: str = ""
    sap_sl_verify_ssl: bool = False

    # WMS SQL Server
    wms_db_server: str = Field(default_factory=lambda: os.getenv("WMS_DB_SERVER") or os.getenv("DB_HOST", ""))
    wms_db_name: str = Field(default_factory=lambda: os.getenv("WMS_DB_NAME") or os.getenv("DB_NAME", ""))
    wms_db_user: str = Field(default_factory=lambda: os.getenv("WMS_DB_USER") or os.getenv("DB_USER", ""))
    wms_db_password: str = Field(default_factory=lambda: os.getenv("WMS_DB_PASSWORD") or os.getenv("DB_PASSWORD", ""))
    wms_db_driver: str = Field(default_factory=lambda: os.getenv("WMS_DB_DRIVER") or os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server"))
    wms_db_encrypt: str = Field(default_factory=lambda: os.getenv("WMS_DB_ENCRYPT") or os.getenv("DB_ENCRYPT", "no"))
    wms_db_trust_server_certificate: str = Field(
        default_factory=lambda: os.getenv("WMS_DB_TRUST_SERVER_CERTIFICATE")
        or os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")
    )

    # Integrator
    config_access_key: str = "changeme"

    # Intervals (seconds)
    interval_items: int = 1800
    interval_wms_items: int = 1800
    interval_partners: int = 1800
    interval_transfers: int = 120
    interval_stock_movements: int = 120
    interval_purchase_orders: int = 120

    # Toggles
    sync_items_enabled: bool = False
    sync_wms_items_enabled: bool = False
    sync_partners_enabled: bool = False
    sync_transfers_enabled: bool = False
    sync_stock_movements_enabled: bool = False
    sync_purchase_orders_enabled: bool = False

    # SAP Series (comma-separated strings → parsed as lists)
    sap_transfer_series: str = ""
    sap_goods_receipt_series: str = ""
    sap_goods_issue_series: str = ""
    sap_purchase_order_series: str = ""
    sap_purchase_order_warehouse_code: str = "001"
    sap_purchase_order_line_ref_field: str = "SEI_DocONS3"

    # Internal DB
    sqlite_db_path: str = str(DEFAULT_SQLITE_DB)

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_secret_key: str = "supersecretkey_change_in_production"

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def transfer_series_list(self) -> List[str]:
        return [s.strip() for s in self.sap_transfer_series.split(",") if s.strip()]

    @property
    def goods_receipt_series_list(self) -> List[str]:
        return [s.strip() for s in self.sap_goods_receipt_series.split(",") if s.strip()]

    @property
    def goods_issue_series_list(self) -> List[str]:
        return [s.strip() for s in self.sap_goods_issue_series.split(",") if s.strip()]

    @property
    def wms_connection_string(self) -> str:
        return (
            f"DRIVER={{{self.wms_db_driver}}};"
            f"SERVER={self.wms_db_server};"
            f"DATABASE={self.wms_db_name};"
            f"UID={self.wms_db_user};"
            f"PWD={self.wms_db_password};"
            f"Encrypt={self.wms_db_encrypt};"
            f"TrustServerCertificate={self.wms_db_trust_server_certificate};"
        )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def update_env_file(updates: dict) -> None:
    """Persist key=value pairs back to .env so they survive restarts."""
    env_path = ENV_FILE
    content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = content.splitlines()

    for key, value in updates.items():
        key_upper = key.upper()
        found = False
        for i, line in enumerate(lines):
            if re.match(rf"^\s*{key_upper}\s*=", line):
                lines[i] = f"{key_upper}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key_upper}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Update os.environ immediately so in-process reads see the new values
    for key, value in updates.items():
        os.environ[key.upper()] = str(value)
    # Invalidate cached settings so next get_settings() reloads from .env
    get_settings.cache_clear()
