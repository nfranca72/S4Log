# S4-API

API em FastAPI para o projeto global `S4-Log`.

## Estrutura

```text
S4-API/
├── app/
│   ├── db/
│   ├── main.py
│   ├── repositories/
│   ├── services/
│   ├── settings.py
│   └── routers/
│       ├── business_partners.py
│       ├── health.py
│       ├── itemmaster.py
│       └── production_control.py
├── .env.example
└── requirements.txt
```

## Como arrancar

```bash
cd S4-API
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Configuração SQL Server

Cria um ficheiro `.env` a partir de `.env.example`.

## Segurança API Key

Gera uma chave forte para entregar ao cliente e guarda no servidor apenas o hash SHA-256 dessa chave.

Exemplo de chave entregue ao cliente:

```env
s4_live_fsm_trocar_por_token_longo
```

Exemplo de configuração no servidor:

```env
API_KEY_HASHES=hash_sha256_da_chave_do_cliente
```

Podes configurar várias chaves separando os hashes por vírgula:

```env
API_KEY_HASHES=hash_cliente_a,hash_cliente_b
```

Todos os endpoints exigem que o cliente envie a chave em claro no header:

```http
X-API-Key: s4_live_fsm_trocar_por_token_longo
```

No Swagger (`/docs`), usa o botão **Authorize** e introduz o valor da chave.

Opção 1: usar a connection string já desencriptada

```env
DB_CONNECTION_STRING=DRIVER={ODBC Driver 17 for SQL Server};SERVER=SERVIDOR;DATABASE=BASE_DADOS;UID=UTILIZADOR;PWD=PASSWORD;TrustServerCertificate=yes;
```

Opção 2: montar a connection string por partes

```env
DB_HOST=SERVIDOR
DB_NAME=BASE_DADOS
DB_USER=UTILIZADOR
DB_PASSWORD=PASSWORD
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_TRUST_SERVER_CERTIFICATE=yes
```

Opção 3: usar a string encriptada do VB.NET

```env
DB_CONNECTION_STRING_ENCRYPTED=...
DB_ENCRYPTION_KEY=OnSearch-OnS3
```

Nota: este último modo já está previsto na configuração, mas ainda precisa da implementação exata da classe VB.NET `Encrypter` para a desencriptação funcionar em Python.

## Configuração SAP B1 Service Layer

```env
SAP_SL_BASE_URL=https://sap-server:50000/b1s/v1
SAP_SL_COMPANY_DB=SBODEMO
SAP_SL_USERNAME=manager
SAP_SL_PASSWORD=secret
SAP_SL_VERIFY_SSL=false
SAP_SL_TIMEOUT_SECONDS=30
# Opcional: campo UDF da linha do documento para guardar localização
SAP_SL_LOCATION_FIELD=U_LocationCode
```

## Configuração BY-PTL para WMS externo

```env
BY_PTL_WMS_URL=https://wms-server/api/byptl
BY_PTL_WMS_VERIFY_SSL=false
BY_PTL_WMS_TIMEOUT_SECONDS=30
BY_PTL_WMS_API_KEY=
BY_PTL_WMS_API_KEY_HEADER=X-API-Key
BY_PTL_WMS_LOGIN_URL=https://byptdev.prhge.com:4700/ws/auth/login
BY_PTL_WMS_LOGIN_USER=ONSEARCH
BY_PTL_WMS_LOGIN_PASSWORD=trocar_password
BY_PTL_WMS_LOGIN_USER_PARAM=usr_id
BY_PTL_WMS_LOGIN_PASSWORD_PARAM=password
BY_PTL_WMS_AUTH_TOKEN_HEADER=Authorization
BY_PTL_WMS_AUTH_TOKEN_PREFIX=Bearer 
```

O endpoint unico da area `BY-PTL` fica disponivel em:

```http
POST /BY-PTL/BYPTL
```

Este endpoint aceita uma acao e os respetivos dados, valida o payload e reencaminha a mensagem para o endpoint unico do WMS externo.
Se `BY_PTL_WMS_LOGIN_URL` estiver preenchido, a API faz primeiro o login no WMS com `usr_id` e `password`, reaproveita a sessao HTTP e, se existir um token no JSON de resposta, envia-o no header configurado.

### Exemplo `PTL_START`

```json
{
  "Action": "PTL_START",
  "Data": {
    "WAVEID": "WAVE-001",
    "PTLID": "PTL-01"
  }
}
```

### Exemplo `PTL_CHANGE`

```json
{
  "Action": "PTL_CHANGE",
  "Data": {
    "WAVEID": "WAVE-001",
    "PTLID": "PTL-02"
  }
}
```

### Exemplo `PACKING_LIST`

Nota: o ultimo payload corresponde a `PACKING_LIST` e nao a `PACKED_BOX`.

```json
{
  "Action": "PACKING_LIST",
  "Data": {
    "WAVEID": "WAVE-001",
    "PTLID": "PTL-01",
    "PACKINGLISTID": "PK-001",
    "ORDERS": [
      {
        "ORDERID": "ORD-001",
        "PTLLIGHT": "A01",
        "VOLUMES": [
          {
            "VOLUMEID": "VOL-001",
            "VOLUMEWEIGHT": 10,
            "VOLUMETYPE": "BOX",
            "USERID": "USR01",
            "VOLUMEDETAIL": [
              {
                "ORDERID": "ORD-001",
                "VOLUMROWID": "1",
                "LINE": "1",
                "ITEMID": "ITEM-001",
                "QUANTITY": 5
              }
            ]
          }
        ]
      }
    ]
  }
}
```

## Endpoints iniciais

- `GET /health` para validar que a API está ativa.
- `GET /health/db` para validar a ligação à base de dados.
- `GET /BusinessPartners/ActiveBusinessPartners?BpType=C&DocTypeArea=PRODUCTION` para listar business partners ativos por tipo e área documental.
- `GET /BusinessPartners/AtiveSubcontratorforItemMaster?ItemId=5TSWWW44254%20CRV%20PANT&BpType=S&DocTypeArea=PLANING` para listar subcontratados ativos para um artigo e área documental.
- `GET /ItemMaster/ActiveItems?PartnerId=2376&PartnerType=C&ProductionType=PRODUCTION&IncludeImage=false&Version=1&ClientSigla=FSM` para listar artigos ativos. Quando `IncludeImage=true`, devolve `HasImage` por artigo em vez do binário da imagem.
- `GET /ItemMaster/Image?ItemId=5TRWWW48993&ClientSigla=FSM&Version=0` para obter diretamente o primeiro anexo do tipo `IMAGE` de um artigo, devolvido como conteúdo binário com o `Content-Type` adequado.
- `GET /ProductionControl/CoonsumptionforItemMasterandBPartner?ItemId=5TRWWW48993&DocTypeArea=PLANING&BpId=10514` para listar abastecimentos, retornos e consumos por artigo e parceiro.
- `GET /ProductionControl/GetProductionEntriesByDates?FromDate=2026-04-01&ToDate=2026-04-30` para listar entradas de produção entre duas datas.
- `POST /ProductionControl/Consumption` para criar consumo de componentes (movimento SAP B1 + espelho na base SQL local), limitando a quantidade à disponibilidade verificada no SAP B1 por armazém e localização/bin antes de atualizar `CONS`, `StockMov` e `Inventory`, e devolvendo no retorno a mensagem final, o número do movimento SAP e o número do documento local `CONS`.
- `GET /docs` para aceder à documentação Swagger gerada automaticamente.

### Exemplo `POST /ProductionControl/Consumption`

```json
{
  "Header": {
    "PartnerID": "10550",
    "Project": "THF.25.SU26.WC.0000",
    "ItemId": "5WCWWW50081 WAISTCOAT",
    "ConsumptionDate": "2026-04-27"
  },
  "Lines": [
    {
      "ComponentId": "5TRWWW48993",
      "QtyConsumir": 12.5
    }
  ]
}
```

## Email resumo de vendas

Configuracao no `.env`:

```env
SALES_DB_CONNECTION_STRING=
SALES_DB_HOST=SERVIDOR_VENDAS
SALES_DB_NAME=BASE_DADOS_VENDAS
SALES_DB_USER=UTILIZADOR_VENDAS
SALES_DB_PASSWORD=PASSWORD_VENDAS
SALES_DB_DRIVER=ODBC Driver 17 for SQL Server
SALES_DB_TRUST_SERVER_CERTIFICATE=yes

SALES_EMAIL_SMTP_SERVER=smtp.gmail.com
SALES_EMAIL_SMTP_PORT=587
SALES_EMAIL_SENDER=seuemail@empresa.pt
SALES_EMAIL_PASSWORD=app_password
SALES_EMAIL_RECIPIENTS=administracao@empresa.pt,financeiro@empresa.pt
SALES_EMAIL_SUBJECT_PREFIX=Resumo de Vendas

SALES_MA_EMAIL_SMTP_SERVER=smtp.gmail.com
SALES_MA_EMAIL_SMTP_PORT=587
SALES_MA_EMAIL_SENDER=relatorios-ma@empresa.pt
SALES_MA_EMAIL_PASSWORD=app_password_ma
SALES_MA_EMAIL_RECIPIENTS=administracao-ma@empresa.pt,financeiro-ma@empresa.pt
SALES_MA_EMAIL_SUBJECT_PREFIX=Resumo de Vendas
```

A base de dados do resumo de vendas e independente da base de dados principal da API. Podes usar `SALES_DB_CONNECTION_STRING` completa ou preencher os campos `SALES_DB_*` separados.

Para Gmail, usa uma App Password. Para Outlook/Office 365, usa `smtp.office365.com`.

Endpoint:

```http
GET /SalesSummary/SendEmail
```

Para validar os dados sem enviar email:

```http
GET /SalesSummary/SendEmail?PreviewOnly=true
```

Para ver o HTML final do email no browser:

```http
GET /SalesSummary/Preview
```

## Email resumo de vendas MA

Usa a mesma configuracao SQL `SALES_DB_*`, mas tem configuracao SMTP propria em `SALES_MA_EMAIL_*`.

Endpoints:

```http
GET /SalesSummaryMA/Companies
GET /SalesSummaryMA/Preview?Company=NOME_EMPRESA
GET /SalesSummaryMA/Preview?Company=NOME_EMPRESA&Date=2026-05-29
GET /SalesSummaryMA/SendEmail?Company=NOME_EMPRESA
GET /SalesSummaryMA/SendEmail?Company=NOME_EMPRESA&PreviewOnly=true
GET /SalesSummaryMA/SendEmail?Company=NOME_EMPRESA&Date=2026-05-29
GET /SalesSummaryMA/SendEmail?Company=NOME_EMPRESA&Recipients=email1@empresa.pt;email2@empresa.pt
```

Os dados sao lidos de `dbo.DocMovsAcum`, filtrando por `COMPANY`. A connection string de vendas deve apontar para a base de dados `Ons3_Dash`.
No `SendEmail`, o parametro `Recipients` aparece no Swagger com os emails configurados em `SALES_MA_EMAIL_RECIPIENTS` e pode ser alterado para essa chamada.
