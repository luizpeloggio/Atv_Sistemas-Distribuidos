# Projeto Incremental (3ª unidade) — Módulo 1: Computação em Nuvem

Disciplina: Sistemas Distribuídos
Integrantes: [NOMES DO GRUPO]

- **URL pública da API:** [COLE AQUI A URL DO RENDER]
- **Documentação interativa:** `[URL]/docs`
- **Vídeo de demonstração (YouTube, não listado):** [COLE AQUI O LINK]

## Domínio

Gerenciador de tarefas. Entidade central: **Tarefa** (`id`, `titulo`, `status`, `responsavel`), com CRUD completo. A mudança de status (por exemplo, `pendente` para `concluida`) será o evento usado no módulo de mensageria.

## Tecnologias

- Python 3 + FastAPI (API REST)
- PostgreSQL gerenciado (Render)
- Hospedagem: Render (deploy direto do GitHub, sem Docker)

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| POST | `/tarefas` | Cria uma tarefa |
| GET | `/tarefas` | Lista as tarefas |
| PUT | `/tarefas/{id}` | Atualiza uma tarefa |
| DELETE | `/tarefas/{id}` | Remove uma tarefa |

## Executar localmente

```bash
cd ATV3/modulo1_nuvem
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgresql://usuario:senha@localhost:5432/tarefas"
uvicorn main:app --reload
```

Para um teste rápido sem PostgreSQL, use `export DATABASE_URL="sqlite:///teste.db"`.

## Deploy no Render

1. **Banco:** New → PostgreSQL (plano Free). Copiar a *Internal Database URL*.
2. **API:** New → Web Service, conectar este repositório e preencher:
   - Root Directory: `ATV3/modulo1_nuvem`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Instance Type: Free
3. **Variável de ambiente** (painel do Render, nada de segredo no código): `DATABASE_URL` = Internal Database URL do banco.

## Testes (API pública)

Substitua `URL` pela URL pública acima.

```bash
curl -X POST URL/tarefas -H "Content-Type: application/json" -d '{"titulo":"Estudar RPC","responsavel":"Luiz"}'
curl URL/tarefas
curl -X PUT URL/tarefas/1 -H "Content-Type: application/json" -d '{"titulo":"Estudar RPC","status":"concluida","responsavel":"Luiz"}'
curl -X DELETE URL/tarefas/1
```

[ADICIONE AQUI OS PRINTS DOS TESTES]

## Observações do plano gratuito

- O serviço entra em repouso após 15 minutos sem acessos; a primeira requisição seguinte leva cerca de 1 minuto.
- O PostgreSQL gratuito do Render expira 30 dias após a criação.
