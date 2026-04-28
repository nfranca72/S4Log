# RFID Bridge

Bridge HTTP/SSE para integração RFID com o backend Python.

## Objetivo

Esta bridge prepara a substituição do `sllurp` por um adapter baseado no SDK oficial da Zebra.

Nesta fase:

- expõe endpoints estáveis para `start`, `stop`, `reset` e `tags`
- expõe stream de eventos em `/rfid/events`
- inclui um provider `Fake` para integração local
- inclui um provider `ZebraSdk` para usar a DLL oficial da Zebra em Windows

## Endpoints

- `GET /health`
- `GET /rfid/config`
- `POST /rfid/start`
- `POST /rfid/stop`
- `POST /rfid/reset`
- `GET /rfid/tags`
- `GET /rfid/events`
- `POST /rfid/mock/tags`

## Providers

- `Fake`: útil para smoke tests locais
- `ZebraSdk`: usa a DLL do Host RFID SDK oficial da Zebra, carregada por reflexão

### Ativar ZebraSdk

1. Instalar o Host RFID SDK oficial da Zebra na máquina Windows
2. Colocar o caminho da DLL em `RfidBridge:ZebraSdk:AssemblyPath`
3. Alterar `RfidBridge:Provider` para `ZebraSdk`

Exemplo:

```json
{
  "RfidBridge": {
    "Provider": "ZebraSdk",
    "Host": "172.16.16.114",
    "Port": 5084,
    "Antennas": [2, 3, 4],
    "ZebraSdk": {
      "AssemblyPath": "C:\\\\Program Files\\\\Zebra RFID SDK\\\\Symbol.RFID3.Host.dll",
      "ReaderTypeName": "Symbol.RFID3.RFIDReader",
      "ConnectionTimeout": 30,
      "PollIntervalMs": 250
    }
  }
}
```

Nota:
- o provider tenta aplicar `TxPower` e `RxSensitivity` quando essas propriedades existem no objeto do SDK
- se a versão concreta do SDK expuser nomes diferentes, a leitura continua a funcionar com os defaults do reader e fica warning nos logs

## Exemplo rápido

```bash
dotnet run
curl -X POST http://127.0.0.1:5000/rfid/start
curl -X POST http://127.0.0.1:5000/rfid/mock/tags \
  -H "Content-Type: application/json" \
  -d '{"tags":["E28068940000501234567890"]}'
curl http://127.0.0.1:5000/rfid/tags
```
