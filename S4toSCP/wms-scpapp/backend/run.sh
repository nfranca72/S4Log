#!/bin/bash
# Instala dependências se necessário
pip install -r requirements.txt

# Arranca o servidor
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
