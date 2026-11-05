#!/usr/bin/env bash
# Sobe os 4 serviços localmente (cada um com seu próprio banco SQLite).
#   usuarios -> :8001   projetos -> :8002   tarefas -> :8003   gateway/painel -> :8000
# Uso: ./run_local.sh      (Ctrl+C encerra tudo)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q fastapi uvicorn sqlalchemy "psycopg[binary]" httpx
fi
mkdir -p .dados
PY=.venv/bin/python

export USUARIOS_URL=http://localhost:8001 PROJETOS_URL=http://localhost:8002 TAREFAS_URL=http://localhost:8003
pids=()
trap 'echo; echo "Encerrando..."; kill "${pids[@]}" 2>/dev/null || true' EXIT INT TERM

sobe() {  # nome porta
  (cd "$1-service" && DATABASE_URL="sqlite:///../.dados/$1.db" \
     ../$PY -m uvicorn main:app --port "$2" --log-level warning) &
  pids+=($!)
}
sobe usuarios 8001
sobe projetos 8002
sobe tarefas 8003
(cd gateway && ../$PY -m uvicorn main:app --port 8000 --log-level warning) &
pids+=($!)

echo "Painel:   http://localhost:8000"
echo "Docs API: http://localhost:8001/docs  8002/docs  8003/docs"
wait
