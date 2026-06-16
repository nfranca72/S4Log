from pydantic import BaseModel


class CompanyCreate(BaseModel):
    tenant_id: str
    name: str
    db_url: str


class CompanyOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    is_active: bool

    model_config = {"from_attributes": True}
