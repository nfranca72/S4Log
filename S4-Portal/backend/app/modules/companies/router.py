from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin, get_master_db
from app.models.master import Company
from app.schemas.auth import UserOut
from app.schemas.company import CompanyCreate, CompanyOut

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=list[CompanyOut])
async def list_companies(
    master_db: AsyncSession = Depends(get_master_db),
    _: UserOut = Depends(get_current_admin),
) -> list[CompanyOut]:
    result = await master_db.execute(select(Company).order_by(Company.name))
    companies = result.scalars().all()
    return [CompanyOut.model_validate(c) for c in companies]


@router.post("/", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreate,
    master_db: AsyncSession = Depends(get_master_db),
    _: UserOut = Depends(get_current_admin),
) -> CompanyOut:
    existing = await master_db.execute(
        select(Company).where(Company.tenant_id == body.tenant_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant '{body.tenant_id}' already exists",
        )

    company = Company(
        tenant_id=body.tenant_id,
        name=body.name,
        db_url=body.db_url,
    )
    master_db.add(company)
    await master_db.commit()
    await master_db.refresh(company)
    return CompanyOut.model_validate(company)


@router.get("/{tenant_id}", response_model=CompanyOut)
async def get_company(
    tenant_id: str,
    master_db: AsyncSession = Depends(get_master_db),
    _: UserOut = Depends(get_current_admin),
) -> CompanyOut:
    result = await master_db.execute(select(Company).where(Company.tenant_id == tenant_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyOut.model_validate(company)
