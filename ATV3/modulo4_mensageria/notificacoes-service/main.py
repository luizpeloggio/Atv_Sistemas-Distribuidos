"""Serviço de notificações — CONSUMIDOR de eventos (Módulo 4: mensageria com RabbitMQ).

Escuta o exchange "taskflow.eventos" (tipo topic) numa fila durável e, para cada evento de tarefa,
apenas confirma o recebimento (log + ACK). Uma pequena API HTTP mostra o que já foi recebido.

Variáveis de ambiente: RABBITMQ_URL (amqp://usuario:senha@host:5672/), PORT.
"""
import json
import logging
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone

import pika
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [notificacoes] %(message)s")
log = logging.getLogger("notificacoes")

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
EXCHANGE = "taskflow.eventos"
FILA = "notificacoes.tarefas"
CHAVES = ("tarefa.*",)  # recebe todos os eventos de tarefa; o foco é tarefa.concluida

recebidos: deque = deque(maxlen=100)   # últimos eventos, mais recentes no fim
contagem: Counter = Counter()
ids_vistos: set = set()                # idempotência: a entrega é "pelo menos uma vez"
estado = {"conectado": False, "desde": None}
lock = threading.Lock()
parar = threading.Event()


def tratar(canal, metodo, propriedades, corpo: bytes) -> None:
    try:
        evento = json.loads(corpo)
        chave = metodo.routing_key
        id_msg = evento.get("id") or propriedades.message_id
    except (ValueError, AttributeError):
        log.error("mensagem inválida descartada: %r", corpo[:80])
        canal.basic_nack(metodo.delivery_tag, requeue=False)   # não adianta reenfileirar lixo
        return

    with lock:
        duplicada = id_msg in ids_vistos
        ids_vistos.add(id_msg)
        if len(ids_vistos) > 5000:
            ids_vistos.clear()
        if not duplicada:
            contagem[chave] += 1
            recebidos.append({"recebido_em": datetime.now(timezone.utc).isoformat(),
                              "chave": chave, "mensagem": evento})
    if duplicada:
        log.info("RECEBIDO (duplicado, ignorado) %s msg=%s", chave, id_msg)
    else:
        dados = evento.get("dados", {})
        if chave == "tarefa.concluida":
            log.info("NOTIFICAÇÃO: tarefa #%s \"%s\" foi CONCLUÍDA (msg=%s rid=%s)",
                     dados.get("id"), dados.get("titulo"), id_msg, evento.get("request_id"))
        else:
            log.info("RECEBIDO %s tarefa #%s (msg=%s)", chave, dados.get("id"), id_msg)
    canal.basic_ack(metodo.delivery_tag)                       # só confirma depois de processar


def consumir() -> None:
    """Loop de conexão: se o broker cair ou ainda não estiver pronto, tenta de novo."""
    while not parar.is_set():
        try:
            conexao = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            canal = conexao.channel()
            canal.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
            canal.queue_declare(queue=FILA, durable=True)
            for chave in CHAVES:
                canal.queue_bind(queue=FILA, exchange=EXCHANGE, routing_key=chave)
            canal.basic_qos(prefetch_count=10)
            canal.basic_consume(queue=FILA, on_message_callback=tratar)
            estado.update(conectado=True, desde=datetime.now(timezone.utc).isoformat())
            log.info("conectado ao RabbitMQ; aguardando eventos na fila %s (%s)", FILA, ", ".join(CHAVES))
            while not parar.is_set():
                conexao.process_data_events(time_limit=1)
            conexao.close()
        except Exception as erro:
            estado["conectado"] = False
            log.warning("RabbitMQ indisponível (%s); nova tentativa em 3 s", erro.__class__.__name__)
            time.sleep(3)
    estado["conectado"] = False


app = FastAPI(title="Notificações (consumidor)", version="1.0")


@app.on_event("startup")
def iniciar() -> None:
    threading.Thread(target=consumir, name="consumidor", daemon=True).start()


@app.on_event("shutdown")
def encerrar() -> None:
    parar.set()


@app.get("/health")
def health():
    return {"status": "ok", "servico": "notificacoes", "rabbitmq_conectado": estado["conectado"]}


@app.get("/eventos")
def eventos(limite: int = 20):
    """Últimos eventos recebidos (mais recentes primeiro)."""
    with lock:
        return {"total": sum(contagem.values()), "por_tipo": dict(contagem),
                "eventos": list(recebidos)[::-1][:max(1, min(limite, 100))]}
