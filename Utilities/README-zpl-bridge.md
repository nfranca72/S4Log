# ZPL TCP Bridge para macOS

Este utilitario permite testar o fluxo atual do `S4toSCP` sem alterar codigo.

O backend continua a enviar ZPL para uma "impressora de rede" em TCP porta `9100`, mas o Mac recebe esse trafego e reencaminha-o para a impressora local instalada no sistema.

## 1. Descobrir o nome da impressora

```bash
lpstat -p
```

Usa exatamente o nome configurado no macOS.

## 2. Arrancar o bridge

```bash
python3 /Users/nunofranca/S4-Log/Utilities/zpl_tcp_bridge.py --printer "NOME_DA_IMPRESSORA"
```

Se quiseres aceitar ligacoes de outras maquinas na rede, mantem o host por defeito `0.0.0.0`.

Se so precisares de testes locais no proprio Mac:

```bash
python3 /Users/nunofranca/S4-Log/Utilities/zpl_tcp_bridge.py --printer "NOME_DA_IMPRESSORA" --host 127.0.0.1
```

## 3. Configurar o destino no `DocumentPrintConfig`

Para testes no mesmo Mac onde corre o backend:

- `PrinterName = 127.0.0.1`

Para testes a partir de outra maquina da rede:

- `PrinterName = <IP_DO_TEU_MAC>`

O porto continua a ser `9100`.

## 4. Testar

Quando o backend mandar imprimir, o bridge deve escrever algo como:

```text
[bridge] recebido job de 127.0.0.1:xxxxx com N bytes
[bridge] job enviado para 'NOME_DA_IMPRESSORA'
```

## Notas

- O bridge tenta primeiro `lp -o raw` e depois faz fallback para `lpr -l`.
- Se a porta `9100` ja estiver ocupada, arranca o bridge noutra porta e ajusta temporariamente o codigo/backend, ou liberta a porta.
- Isto e apenas para testes locais. Em producao, o ideal e continuar a apontar para a impressora Zebra de rede.
