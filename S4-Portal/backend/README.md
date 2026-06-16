# S4Log Portal – Backend

FastAPI multi-tenant backend para o portal B2B S4Log.

## Arquitectura

- **Master DB** (`s4log_master`): regista empresas (`companies`) e utilizadores (`users`)
- **Tenant DB** (por empresa): base de dados PostgreSQL separada por tenant
- **Tenant resolution**: subdomínio do `Host` header (ex: `demo.s4log.app` → `tenant_id = demo`)
- **Auth**: JWT (HS256) com `sub` (email) + `tenant_id`

## Arranque rápido

```bash
# 1. Criar e activar virtualenv
python -m venv .venv
source .venv/bin/activate

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.example .env
# editar .env com as credenciais reais

# 4. Criar tabelas e dados de teste
python seed.py

# 5. Arrancar o servidor
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Endpoints principais

| Método | Path | Descrição |
|--------|------|-----------|
| POST | `/api/v1/auth/login` | Login – devolve JWT |
| GET  | `/api/v1/auth/me` | Dados do utilizador autenticado |
| GET  | `/api/v1/companies/` | Lista empresas (admin) |
| POST | `/api/v1/companies/` | Cria empresa (admin) |
| GET  | `/api/v1/companies/{tenant_id}` | Detalhes de empresa (admin) |
| GET  | `/health` | Health check |

Documentação interactiva: http://localhost:8000/docs

## Tenant em desenvolvimento local

Para testar com o tenant `demo` sem DNS:

```bash
curl -H "Host: demo.s4log.app" http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.s4log.app","password":"Demo1234!"}'
```

## Estrutura

```
app/
  core/        config, security (JWT/bcrypt), deps (FastAPI DI)
  db/          master engine + tenant pool dinâmico
  middleware/  extracção do tenant_id do Host header
  models/      SQLAlchemy ORM (master: Company, User)
  schemas/     Pydantic v2 (auth, company)
  modules/     routers por domínio (auth, companies)
```
