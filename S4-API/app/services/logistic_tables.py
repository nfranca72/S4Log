from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.models.logistic_tables import VolumeRequest, VolumeResponse
from app.repositories.logistic_tables import create_or_update_volume


def create_update_volume(payload: VolumeRequest) -> VolumeResponse:
    volume = _quantize_2(payload.length * payload.height * payload.width)

    result = create_or_update_volume(
        volume_type=payload.volume_type,
        length=_quantize_2(payload.length),
        height=_quantize_2(payload.height),
        width=_quantize_2(payload.width),
        net_weight=_quantize_2(payload.net_weight) if payload.net_weight is not None else None,
        volume=volume,
        vol_doc_cod=payload.vol_doc_cod or "CX",
    )

    return VolumeResponse(**result)


def _quantize_2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
