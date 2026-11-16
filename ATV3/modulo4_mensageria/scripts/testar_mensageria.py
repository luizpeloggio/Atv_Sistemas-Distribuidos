#!/usr/bin/env python3
"""Teste do fluxo de mensageria (produtor -> RabbitMQ -> consumidor). Só biblioteca padrão.

Uso (com o Compose do Módulo 4 no ar):
    python3 scripts/testar_mensageria.py                 # fluxo básico
    python3 scripts/testar_mensageria.py --resiliencia   # + consumidor offline + broker offline
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

GATEWAY = "http://localhost:8000"
CONSUMIDOR = "http://localhost:8004"
falhas = 0


def req(metodo, url, corpo=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(url, data=dados, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            texto = resp.read().decode()
            return resp.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def ok(condicao, texto):
    global falhas
    print(f"  [{'OK' if condicao else 'FALHOU'}] {texto}")
    falhas += 0 if condicao else 1
    return condicao


def eventos_da_tarefa(tid):
    _, d = req("GET", f"{CONSUMIDOR}/eventos?limite=100")
    return {e["chave"] for e in (d or {}).get("eventos", []) if e["mensagem"]["dados"].get("id") == tid}


def esperar(tid, chaves, segundos=15):
    fim = time.time() + segundos
    while time.time() < fim:
        if set(chaves) <= eventos_da_tarefa(tid):
            return True
        time.sleep(0.5)
    return False


def compose(*args):
    subprocess.run(["docker", "compose", *args], check=True, capture_output=True)


def esperar_saudavel(servico, segundos=60):
    fim = time.time() + segundos
    while time.time() < fim:
        r = subprocess.run(["docker", "compose", "ps", "--format", "{{.Health}}", servico],
                           capture_output=True, text=True)
        if r.stdout.strip() == "healthy":
            return True
        time.sleep(2)
    return False


def main():
    resiliencia = "--resiliencia" in sys.argv
    print("1) Consumidor e gateway no ar")
    s, h = req("GET", f"{CONSUMIDOR}/health")
    if not ok(s == 200 and h and h["rabbitmq_conectado"], "consumidor conectado ao RabbitMQ"):
        sys.exit("O consumidor não está conectado. Rode: docker compose up -d --build --wait")

    print("\n2) Produtor -> broker -> consumidor (evento real: tarefa concluída)")
    s, t = req("POST", f"{GATEWAY}/api/tarefas", {"titulo": "Teste de mensageria", "prioridade": "alta"})
    ok(s == 201, "tarefa criada via API (201)")
    tid = t["id"]
    ok(esperar(tid, ["tarefa.criada"]), "consumidor recebeu tarefa.criada")
    s, _ = req("PATCH", f"{GATEWAY}/api/tarefas/{tid}", {"status": "concluida"})
    ok(s == 200, "status alterado para concluída (200)")
    ok(esperar(tid, ["tarefa.status_alterado", "tarefa.concluida"]),
       "consumidor recebeu tarefa.status_alterado e tarefa.concluida")
    req("DELETE", f"{GATEWAY}/api/tarefas/{tid}")
    ok(esperar(tid, ["tarefa.removida"]), "consumidor recebeu tarefa.removida")

    if resiliencia:
        print("\n3) Consumidor OFFLINE: a mensagem espera na fila durável")
        compose("stop", "notificacoes")
        s, t2 = req("POST", f"{GATEWAY}/api/tarefas", {"titulo": "Enquanto o consumidor está fora", "status": "concluida"})
        ok(s == 201, "produtor continua publicando (API responde 201)")
        compose("start", "notificacoes")
        ok(esperar_saudavel("notificacoes"), "consumidor voltou a ficar saudável")
        ok(esperar(t2["id"], ["tarefa.concluida"], 30),
           "mensagem acumulada foi entregue depois que o consumidor voltou (desacoplamento no tempo)")
        req("DELETE", f"{GATEWAY}/api/tarefas/{t2['id']}")

        print("\n4) RabbitMQ OFFLINE: a API não pode quebrar")
        compose("stop", "rabbitmq")
        inicio = time.time()
        s, t3 = req("POST", f"{GATEWAY}/api/tarefas", {"titulo": "Sem broker"})
        ok(s == 201, f"API continua respondendo 201 com o broker fora ({time.time() - inicio:.1f} s)")
        if t3:
            req("DELETE", f"{GATEWAY}/api/tarefas/{t3['id']}")
        compose("start", "rabbitmq")
        ok(esperar_saudavel("rabbitmq", 90), "RabbitMQ voltou a ficar saudável")

    print()
    if falhas:
        sys.exit(f"{falhas} verificação(ões) falharam")
    print("TODOS OS TESTES PASSARAM")


if __name__ == "__main__":
    main()
