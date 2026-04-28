from fastapi import APIRouter, HTTPException, Query, Response
from typing import Optional

from app.services.itemmaster import get_item_image, list_active_items

router = APIRouter(prefix="/ItemMaster", tags=["ItemMaster"])


@router.get(
    "/ActiveItems",
    summary="List active items for a given partner and production area",
)
def get_active_items(
    partner_id: str = Query(..., alias="PartnerId", min_length=1, max_length=10),
    partner_type: str = Query(..., alias="PartnerType", min_length=1, max_length=1),
    production_type: str = Query(..., alias="ProductionType", min_length=1, max_length=20),
    include_image: bool = Query(False, alias="IncludeImage"),
    version: Optional[int] = Query(None, alias="Version"),
    client_sigla: Optional[str] = Query(None, alias="ClientSigla", min_length=1, max_length=20),
) -> list[dict[str, object]]:
    try:
        return list_active_items(
            partner_id=partner_id,
            partner_type=partner_type,
            production_type=production_type,
            include_image=include_image,
            version=version,
            client_sigla=client_sigla,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active items: {exc}",
        ) from exc


@router.get(
    "/Image",
    summary="Get the first image attachment for an item",
)
def get_image(
    item_id: str = Query(..., alias="ItemId", min_length=1, max_length=50),
    client_sigla: str = Query(..., alias="ClientSigla", min_length=1, max_length=20),
    version: Optional[int] = Query(None, alias="Version"),
) -> Response:
    try:
        image = get_item_image(
            item_id=item_id,
            client_sigla=client_sigla,
            version=version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch item image: {exc}",
        ) from exc

    if image is None:
        raise HTTPException(status_code=404, detail="Image not found for the given item")

    return Response(
        content=image["content"],
        media_type=str(image["media_type"]),
    )
