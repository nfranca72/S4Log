from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from typing import Optional

from app.services.itemmaster import (
    get_item_image,
    list_active_items,
    list_active_items_for_client,
    list_item_active_production_orders,
    list_item_versions,
    list_itemmaster,
    save_item_attachment,
)

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


@router.post(
    "/Attachments",
    summary="Save a file attachment for an item version",
)
async def post_item_attachment(
    request: Request,
    company: Optional[str] = Form(None, min_length=1, max_length=20),
    item_id: Optional[str] = Form(None, min_length=1, max_length=100),
    version: Optional[int] = Form(None, ge=0),
    observation: str = Form("", max_length=500),
    user_id: str = Form("", alias="UserID", max_length=50),
    file: UploadFile = File(...),
) -> dict[str, object]:
    try:
        form = await request.form()
        fields = {key.upper(): value for key, value in form.multi_items()}

        resolved_company = company or _form_text(fields.get("COMPANY"))
        resolved_item_id = (
            item_id
            or _form_text(fields.get("ITEMID"))
            or _form_text(fields.get("ITEM_ID"))
            or _form_text(fields.get("ARTIGO"))
        )
        resolved_version = version if version is not None else _form_text(fields.get("VERSION"))
        resolved_observation = observation or _form_text(fields.get("OBSERVATION")) or ""
        resolved_user_id = user_id or _form_text(fields.get("USERID")) or _form_text(fields.get("USER_ID")) or ""
        resolved_file = file

        if not resolved_company:
            raise ValueError("Company is required")
        if not resolved_item_id:
            raise ValueError("ItemID or Artigo is required")
        if resolved_version is None:
            raise ValueError("Version is required")
        version = int(resolved_version)
        if version < 0:
            raise ValueError("Version must be greater than or equal to zero")

        content = await resolved_file.read()
        return save_item_attachment(
            company=resolved_company,
            item_id=resolved_item_id,
            version=version,
            observation=resolved_observation,
            user_id=resolved_user_id,
            file_name=resolved_file.filename or "",
            file_content=content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save item attachment: {exc}",
        ) from exc


@router.get(
    "/List",
    summary="List ItemMaster records with optional filters",
)
def get_itemmaster_list(
    show_items_components: bool = Query(True, alias="ShowItemsComponents"),
    show_items_composed: bool = Query(True, alias="ShowItemsComposed"),
    show_all_versions: bool = Query(False, alias="ShowAllVersions"),
    restrict_to_component: str = Query("", alias="RestrictToThisItemIDHasComponent", max_length=100),
    page_number: int = Query(1, alias="PageNumber", ge=1),
    page_size: int = Query(50, alias="PageSize", ge=1, le=1000),
    include_total_count: bool = Query(False, alias="IncludeTotalCount"),
    sort_by: str = Query("", alias="SortBy", max_length=100),
    item_budget: str = Query("", alias="ItemBudget", max_length=50),
    item_id: Optional[str] = Query(None, alias="ItemID", max_length=100),
    item_desc: Optional[str] = Query(None, alias="ItemDesc", max_length=250),
    client_ref: Optional[str] = Query(None, alias="ClientRef", max_length=100),
    modelo: Optional[str] = Query(None, alias="Modelo", max_length=100),
    category_id: Optional[str] = Query(None, alias="CategoryID", max_length=50),
    category_desc: Optional[str] = Query(None, alias="CategoryDesc", max_length=100),
    subcategory_id: Optional[str] = Query(None, alias="SubCategoryId", max_length=50),
    subcategory_descr: Optional[str] = Query(None, alias="SubCategoryDescr", max_length=100),
    brand_id: Optional[str] = Query(None, alias="BrandID", max_length=50),
    brand_desc: Optional[str] = Query(None, alias="BrandDesc", max_length=100),
    version: Optional[int] = Query(None, alias="Version"),
    version_name: Optional[str] = Query(None, alias="VersionName", max_length=100),
    qty: Optional[float] = Query(None, alias="Qty"),
    stk_unit: Optional[str] = Query(None, alias="StkUnit", max_length=20),
    unit_desc: Optional[str] = Query(None, alias="UnitDesc", max_length=100),
    lots: Optional[bool] = Query(None, alias="Lots"),
    item_has_serial_nums: Optional[bool] = Query(None, alias="ItemHasSerialNums"),
    item_has_vol_nums: Optional[bool] = Query(None, alias="ItemHasVolNums"),
    barcode: Optional[str] = Query(None, alias="Barcode", max_length=100),
    creation_datetime: Optional[str] = Query(None, alias="CreationDateTime", max_length=30),
    modif_datetime: Optional[str] = Query(None, alias="ModifDateTime", max_length=30),
) -> dict[str, object]:
    filters = {
        "ItemID": item_id,
        "ItemDesc": item_desc,
        "ClientRef": client_ref,
        "Modelo": modelo,
        "CategoryID": category_id,
        "CategoryDesc": category_desc,
        "SubCategoryId": subcategory_id,
        "SubCategoryDescr": subcategory_descr,
        "BrandID": brand_id,
        "BrandDesc": brand_desc,
        "Version": version,
        "VersionName": version_name,
        "Qty": qty,
        "StkUnit": stk_unit,
        "UnitDesc": unit_desc,
        "Lots": lots,
        "ItemHasSerialNums": item_has_serial_nums,
        "ItemHasVolNums": item_has_vol_nums,
        "Barcode": barcode,
        "CreationDateTime": creation_datetime,
        "ModifDateTime": modif_datetime,
    }
    try:
        return list_itemmaster(
            filters=filters,
            show_items_components=show_items_components,
            show_items_composed=show_items_composed,
            show_all_versions=show_all_versions,
            restrict_to_this_item_id_has_component=restrict_to_component,
            page_number=page_number,
            page_size=page_size,
            sort_by=sort_by,
            item_budget=item_budget,
            include_total_count=include_total_count,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch ItemMaster list: {exc}",
        ) from exc


@router.get(
    "/GETITEMVERSIONS",
    summary="Get versions for an item",
)
def get_item_versions(
    item_id: str = Query(..., alias="ItemID", min_length=1, max_length=100),
) -> list[dict[str, object]]:
    try:
        return list_item_versions(item_id=item_id)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch item versions: {exc}",
        ) from exc


@router.get(
    "/ActiveItemsByClient",
    summary="List active production items for a client",
)
def get_active_items_by_client(
    client_id: str = Query(..., alias="ClientID", min_length=1, max_length=50),
    page_size: int = Query(50, alias="PageSize", ge=1, le=1000),
    page_number: int = Query(1, alias="PageNumber", ge=1),
) -> dict[str, object]:
    try:
        return list_active_items_for_client(
            client_id=client_id,
            page_number=page_number,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active items for client: {exc}",
        ) from exc


@router.get(
    "/GetItemActiveProductionOrdersList",
    summary="List active production orders for an item",
)
def get_item_active_production_orders_list(
    item_id: str = Query(..., alias="ItemID", min_length=1, max_length=100),
    page_number: int = Query(0, alias="PageNumber", ge=0),
    page_size: int = Query(50, alias="PageSize", ge=1, le=1000),
) -> dict[str, object]:
    try:
        return list_item_active_production_orders(
            item_id=item_id,
            page_number=page_number,
            page_size=page_size,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch active production orders for item: {exc}",
        ) from exc


def _form_text(value: object) -> Optional[str]:
    if value is None or isinstance(value, UploadFile):
        return None

    text = str(value).strip()
    return text or None
