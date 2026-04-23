# Warehouse Frontend

Interface React para gestão de armazém — Módulo 1 (Importação CSV) e Módulo 2 (Receção RFID).

## Pré-requisitos

- Node.js 18+
- npm 9+
- Backend FastAPI a correr em `http://localhost:8000`

## Instalação

```bash
npm install
```

## Desenvolvimento

```bash
npm run dev
```

A aplicação fica disponível em `http://localhost:3000`.  
O Vite faz proxy automático de `/api/*` para `http://localhost:8000/*` — não precisas de configurar CORS durante o desenvolvimento.

## Build para produção

```bash
npm run build
```

Os ficheiros ficam em `dist/`. Serve com qualquer servidor estático (nginx, serve, etc.).

## Estrutura

```
src/
├── App.jsx                        ← Routing principal
├── main.jsx                       ← Entry point
├── index.css                      ← CSS global + variáveis
├── context/
│   └── ToastContext.jsx           ← Sistema de notificações
├── services/
│   └── api.js                     ← Todas as chamadas ao backend
├── components/
│   ├── layout/
│   │   └── Layout.jsx             ← Sidebar + estrutura da página
│   └── ui/
│       └── index.jsx              ← Componentes reutilizáveis (Btn, Card, Badge, etc.)
└── pages/
    ├── Module1.jsx                ← Importação CSV (4 passos)
    └── Module2.jsx                ← Receção RFID (em desenvolvimento)
```

## Módulo 1 — Importação CSV

Fluxo de 4 passos:

1. **Upload** — drag & drop ou clique para selecionar o ficheiro CSV Nike
2. **Preview & Cliente** — visualização de todas as linhas com estado (novo/existe), estatísticas e seleção do cliente
3. **Artigos** — lista dos artigos novos a criar automaticamente no ItemMaster
4. **Resultado** — confirmação da importação com nº do packing criado e validação de quantidades

## Módulo 2 — Receção (próxima fase)

- Seleção de packing list existente
- Conferência por caixa com leitura de código de barras
- Integração RFID Zebra 7500 via WebSocket
- Emissão de etiquetas após conferência
