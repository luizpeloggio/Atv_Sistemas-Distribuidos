#!/usr/bin/env python3
"""Teste de integração: verifica a comunicação entre os microsserviços pelo gateway.

Uso:
    python3 scripts/testar_comunicacao.py                       # local (http://localhost:8000)
    python3 scripts/testar_comunicacao.py https://sd-gateway.onrender.com   # nuvem

Só usa a biblioteca padrão do Python. Cria dados de teste e remove tudo no final.
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
resultados = []


def chamar(metodo, caminho, corpo=None, timeout=90):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(f"{BASE}/api/{caminho}", data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            texto = r.read().decode()
            return r.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        texto = e.read().decode()
        return e.code, (json.loads(texto) if texto else None)


def checar(descricao, condicao, detalhe=""):
    resultados.append(bool(condicao))
    print(f"  [{'OK' if condicao else 'FALHOU'}] {descricao}" + (f"  -> {detalhe}" if detalhe and not condicao else ""))


print(f"Testando {BASE}\n")
print("1) Saúde dos serviços (acorda os serviços gratuitos do Render, pode levar ~1 min)")
st, d = chamar("GET", "status")
checar("gateway responde", st == 200, st)
for s in d["servicos"]:
    checar(f"serviço de {s['servico']} online ({s['latencia_ms']} ms)", s["status"] == "online")

sufixo = str(int(time.time()))
criados = {}
print("\n2) Criação de dados em serviços diferentes")
st, u = chamar("POST", "usuarios", {"nome": "Teste Integração", "email": f"teste{sufixo}@exemplo.com", "cargo": "QA"})
checar("usuário criado no serviço de usuários (201)", st == 201, u); criados["usuarios"] = u["id"]
st, p = chamar("POST", "projetos", {"nome": f"Projeto Teste {sufixo}", "cor": "#22c55e"})
checar("projeto criado no serviço de projetos (201)", st == 201, p); criados["projetos"] = p["id"]

print("\n3) Serviço de tarefas consulta os outros dois por HTTP")
st, t = chamar("POST", "tarefas", {"titulo": "Tarefa de integração", "responsavel_id": u["id"], "projeto_id": p["id"], "prioridade": "alta"})
checar("tarefa criada com referências válidas (201)", st == 201, t); criados["tarefas"] = t["id"]
checar("resposta traz o NOME do responsável (veio do serviço de usuários)", t["responsavel"]["nome"] == "Teste Integração")
checar("resposta traz o NOME do projeto (veio do serviço de projetos)", t["projeto"]["nome"] == p["nome"])

print("\n4) Validação entre serviços")
st, e = chamar("POST", "tarefas", {"titulo": "Responsável fantasma", "responsavel_id": 999999})
checar("responsável inexistente é recusado (422)", st == 422, (st, e))
st, e = chamar("POST", "tarefas", {"titulo": "Projeto fantasma", "projeto_id": 999999})
checar("projeto inexistente é recusado (422)", st == 422, (st, e))

print("\n5) Mudança de estado e estatísticas")
st, t2 = chamar("PATCH", f"tarefas/{t['id']}", {"status": "concluida"})
checar("status alterado para concluída", st == 200 and t2["status"] == "concluida" and t2["concluida_em"], t2)
st, est = chamar("GET", "tarefas/estatisticas")
checar("estatísticas retornam total e por_status", st == 200 and est["total"] >= 1 and "concluida" in est["por_status"], est)
st, r = chamar("GET", "resumo")
checar("gateway agrega dados dos 3 serviços (/api/resumo)", st == 200 and r["usuarios"] is not None and r["projetos"] is not None and r["tarefas"] is not None, r)

print("\n6) Limpeza")
for recurso in ("tarefas", "projetos", "usuarios"):
    st, _ = chamar("DELETE", f"{recurso}/{criados[recurso]}")
    checar(f"{recurso[:-1]} de teste removido (204)", st == 204, st)

ok = all(resultados)
print(f"\n{'TODOS OS TESTES PASSARAM' if ok else 'HÁ FALHAS'} ({sum(resultados)}/{len(resultados)})")
print("\nTeste de falha (manual): desligue o serviço de usuários e rode de novo:")
print("  - criar tarefa com responsável  -> HTTP 503 com mensagem amigável")
print("  - listar tarefas (GET /api/tarefas) -> HTTP 200, responsáveis marcados como 'indisponivel'")
sys.exit(0 if ok else 1)
