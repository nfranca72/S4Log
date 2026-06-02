from __future__ import annotations

from typing import Any

from app.repositories.production_setup import fetch_production_type


def get_production_type(
    production_type: str = "",
    indentification_code: str = "",
) -> list[dict[str, Any]]:
    return fetch_production_type(
        production_type=production_type,
        indentification_code=indentification_code,
    )
