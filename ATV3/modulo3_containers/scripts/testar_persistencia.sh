#!/usr/bin/env bash
# Prova que os dados sobrevivem a "docker compose down" + "docker compose up".
# Uso: ./scripts/testar_persistencia.sh          (precisa de Docker, curl e python3)
set -euo pipefail
cd "$(dirname "$0")/.."
G=${1:-http://localhost:8000}

contar() {  # imprime "usuarios projetos tarefas"
  curl -fsS "$G/api/resumo" | python3 -c \
    "import sys, json; d = json.load(sys.stdin); print(d['usuarios'], d['projetos'], d['tarefas']['total'])"
}

echo "1) Subindo os containers (build + espera ficarem saudáveis)..."
docker compose up -d --build --wait

echo "2) Garantindo que existam dados (carga de demonstração, só se estiver vazio)..."
curl -fsS -X POST "$G/api/demo"; echo
ANTES=$(contar)
echo "   Antes do down  -> usuários/projetos/tarefas: $ANTES"

echo "3) docker compose down (remove containers e rede, mas NÃO os volumes)..."
docker compose down
docker volume ls --filter name=taskflow_pg --format '   volume preservado: {{.Name}}'

echo "4) docker compose up (containers novos, mesmos volumes)..."
docker compose up -d --wait
DEPOIS=$(contar)
echo "   Depois do up   -> usuários/projetos/tarefas: $DEPOIS"

if [ "$ANTES" = "$DEPOIS" ]; then
  echo "OK: os dados persistiram."
else
  echo "FALHOU: os dados mudaram." >&2; exit 1
fi
echo
echo "Para apagar também os dados:  docker compose down -v"
