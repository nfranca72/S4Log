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

## Endpoints iniciais

- `GET /health` para validar que a API está ativa.
- `GET /health/db` para validar a ligação à base de dados.
- `GET /BusinessPartners/ActiveBusinessPartners?BpType=C&DocTypeArea=PRODUCTION` para listar business partners ativos por tipo e área documental.
- `GET /BusinessPartners/AtiveSubcontratorforItemMaster?ItemId=5TSWWW44254%20CRV%20PANT&BpType=S&DocTypeArea=PLANING` para listar subcontratados ativos para um artigo e área documental.
- `GET /ItemMaster/ActiveItems?PartnerId=2376&PartnerType=C&ProductionType=PRODUCTION&IncludeImage=false&Version=1&ClientSigla=FSM` para listar artigos ativos. Quando `IncludeImage=true`, devolve `HasImage` por artigo em vez do binário da imagem.
- `GET /ItemMaster/Image?ItemId=5TRWWW48993&ClientSigla=FSM&Version=0` para obter diretamente o primeiro anexo do tipo `IMAGE` de um artigo, devolvido como conteúdo binário com o `Content-Type` adequado.
- `GET /ProductionControl/CoonsumptionforItemMasterandBPartner?ItemId=5TRWWW48993&DocTypeArea=PLANING&BpId=10514` para listar abastecimentos, retornos e consumos por artigo e parceiro.
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
