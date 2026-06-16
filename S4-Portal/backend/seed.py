"""Seed script – cria empresa 'demo' e utilizador admin de teste.

Uso:
    python seed.py

Requer que a MASTER_DATABASE_URL esteja definida no .env (ou variáveis de ambiente).
"""

import asyncio
import os
import sys

# Permite executar a partir da raiz do projecto sem instalar o pacote
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.master import AsyncSessionLocal, Base, engine
from app.models.master import Company, User  # noqa: F401 – garante registo dos modelos


DEMO_TENANT_ID = "demo"
DEMO_DB_URL = settings.MASTER_DATABASE_URL.replace("/s4log_master", "/s4log_demo")
ADMIN_EMAIL = "admin@demo.s4log.app"
ADMIN_PASSWORD = "Demo1234!"


async def seed() -> None:
    # Cria tabelas se ainda não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # --- Empresa demo ---
        result = await session.execute(select(Company).where(Company.tenant_id == DEMO_TENANT_ID))
        company = result.scalar_one_or_none()
        if company is None:
            company = Company(
                tenant_id=DEMO_TENANT_ID,
                name="Demo Company",
                db_url=DEMO_DB_URL,
            )
            session.add(company)
            print(f"[seed] Empresa criada: {DEMO_TENANT_ID}")
        else:
            print(f"[seed] Empresa já existe: {DEMO_TENANT_ID}")

        # --- Utilizador admin ---
        result = await session.execute(
            select(User).where(User.email == ADMIN_EMAIL, User.tenant_id == DEMO_TENANT_ID)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=ADMIN_EMAIL,
                hashed_password=hash_password(ADMIN_PASSWORD),
                tenant_id=DEMO_TENANT_ID,
                is_admin=True,
            )
            session.add(user)
            print(f"[seed] Utilizador criado: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            print(f"[seed] Utilizador já existe: {ADMIN_EMAIL}")

        await session.commit()

    await engine.dispose()
    print("[seed] Concluído.")


if __name__ == "__main__":
    asyncio.run(seed())
