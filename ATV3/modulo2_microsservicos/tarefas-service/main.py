"""Microsserviço de TAREFAS (entidade central do domínio).

Guarda apenas os dados das tarefas e o ID do responsável e do projeto.
Os dados de usuários e projetos vivem em OUTROS serviços e são consultados por
HTTP (chamada síncrona). Se um deles estiver fora do ar:
  * ao CRIAR/EDITAR uma tarefa com referência -> erro 503 com mensagem amigável;
  * ao LISTAR tarefas -> a lista é devolvida mesmo assim ("degradação graciosa"),
    com a referência marcada como indisponível.
Banco próprio: schema "tarefas" (PostgreSQL) ou arquivo SQLite local.
"""
import logging
import os
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, Date, DateTime, Integer, MetaData, String, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

NOME_SERVICO = "tarefas"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [tarefas] %(message)s")
log = logging.getLogger(NOME_SERVICO)
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

USUARIOS_URL = os.getenv("USUARIOS_URL", "http://localhost:8001").rstrip("/")
PROJETOS_URL = os.getenv("PROJETOS_URL", "http://localhost:8002").rstrip("/")
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "8"))  # segundos por chamada entre serviços

# ----------------------------------------------------------------- banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tarefas.db")
for prefixo in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(prefixo):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(prefixo):]
        break
EH_POSTGRES = DATABASE_URL.startswith("postgresql")
SCHEMA = os.getenv("DB_SCHEMA", "tarefas") if EH_POSTGRES else None

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if not EH_POSTGRES else {},
)
if SCHEMA:
    with engine.begin() as conexao:
        conexao.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
Base = declarative_base(metadata=MetaData(schema=SCHEMA))
Session = sessionmaker(bind=engine)

STATUS = ("pendente", "em_andamento", "concluida")
PRIORIDADES = ("baixa", "media", "alta")


class Tarefa(Base):
    __tablename__ = "tarefas"
    id = Column(Integer, primary_key=True)
    titulo = Column(String, nullable=False)
    descricao = Column(String, default="")
    status = Column(String, default="pendente")
    prioridade = Column(String, default="media")
    responsavel_id = Column(Integer, nullable=True)  # referência (sem FK): vive em outro serviço
    projeto_id = Column(Integer, nullable=True)      # referência (sem FK): vive em outro serviço
    prazo = Column(Date, nullable=True)
    criado_em = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    concluida_em = Column(DateTime, nullable=True)


Base.metadata.create_all(engine)


# ----------------------------------------------------------------------- modelos
class TarefaIn(BaseModel):
    titulo: str = Field(min_length=2, max_length=120)
    descricao: str = Field(default="", max_length=500)
    status: Literal["pendente", "em_andamento", "concluida"] = "pendente"
    prioridade: Literal["baixa", "media", "alta"] = "media"
    responsavel_id: int | None = None
    projeto_id: int | None = None
    prazo: date | None = None


class TarefaPatch(BaseModel):
    titulo: str | None = Field(default=None, min_length=2, max_length=120)
    descricao: str | None = Field(default=None, max_length=500)
    status: Literal["pendente", "em_andamento", "concluida"] | None = None
    prioridade: Literal["baixa", "media", "alta"] | None = None
    responsavel_id: int | None = None
    projeto_id: int | None = None
    prazo: date | None = None


# ------------------------------------------------- comunicação com outros serviços
NOMES_LEGIVEIS = {"usuarios": "usuários", "projetos": "projetos"}


class ServicoIndisponivel(Exception):
    def __init__(self, servico: str):
        self.servico = servico


def chamar(servico: str, base: str, caminho: str) -> httpx.Response:
    """GET síncrono em outro microsserviço, com timeout e propagação do X-Request-ID."""
    try:
        resposta = httpx.get(
            f"{base}{caminho}",
            timeout=TIMEOUT,
            headers={"X-Request-ID": request_id_ctx.get()},
        )
    except httpx.HTTPError as erro:
        log.warning("falha ao chamar o serviço de %s: %s", servico, erro.__class__.__name__)
        raise ServicoIndisponivel(servico)
    if resposta.status_code >= 500:
        log.warning("serviço de %s respondeu %s", servico, resposta.status_code)
        raise ServicoIndisponivel(servico)
    return resposta


def validar_referencias(responsavel_id: int | None, projeto_id: int | None) -> None:
    if responsavel_id is not None:
        if chamar("usuarios", USUARIOS_URL, f"/usuarios/{responsavel_id}").status_code == 404:
            raise HTTPException(422, f"O responsável {responsavel_id} não existe")
    if projeto_id is not None:
        if chamar("projetos", PROJETOS_URL, f"/projetos/{projeto_id}").status_code == 404:
            raise HTTPException(422, f"O projeto {projeto_id} não existe")


def mapa_remoto(servico: str, base: str, recurso: str) -> tuple[dict, bool]:
    """Busca a lista completa de um recurso e devolve {id: objeto}, disponivel."""
    try:
        resposta = chamar(servico, base, f"/{recurso}")
        return {item["id"]: item for item in resposta.json()}, True
    except ServicoIndisponivel:
        return {}, False


def referencia(id_: int | None, mapa: dict, disponivel: bool) -> dict | None:
    if id_ is None:
        return None
    if not disponivel:
        return {"id": id_, "indisponivel": True}
    return mapa.get(id_, {"id": id_, "removido": True})


def dados_base(t: Tarefa) -> dict:
    return {
        "id": t.id, "titulo": t.titulo, "descricao": t.descricao, "status": t.status,
        "prioridade": t.prioridade, "responsavel_id": t.responsavel_id, "projeto_id": t.projeto_id,
        "prazo": t.prazo.isoformat() if t.prazo else None,
        "criado_em": t.criado_em.isoformat() if t.criado_em else None,
        "concluida_em": t.concluida_em.isoformat() if t.concluida_em else None,
    }


def enriquecer(tarefas: list[Tarefa], resposta: Response) -> list[dict]:
    """Junta, a cada tarefa, os dados do responsável e do projeto (vindos de outros serviços)."""
    precisa_usuarios = any(t.responsavel_id is not None for t in tarefas)
    precisa_projetos = any(t.projeto_id is not None for t in tarefas)
    usuarios, ok_u = mapa_remoto("usuarios", USUARIOS_URL, "usuarios") if precisa_usuarios else ({}, True)
    projetos, ok_p = mapa_remoto("projetos", PROJETOS_URL, "projetos") if precisa_projetos else ({}, True)
    degradados = [nome for nome, ok in (("usuarios", ok_u), ("projetos", ok_p)) if not ok]
    if degradados:
        resposta.headers["X-Servicos-Degradados"] = ",".join(degradados)
    saida = []
    for t in tarefas:
        d = dados_base(t)
        d["responsavel"] = referencia(t.responsavel_id, usuarios, ok_u)
        d["projeto"] = referencia(t.projeto_id, projetos, ok_p)
        saida.append(d)
    return saida


# --------------------------------------------------------------------------- app
app = FastAPI(title="Serviço de Tarefas", version="2.0")


@app.exception_handler(ServicoIndisponivel)
async def tratar_indisponivel(request: Request, exc: ServicoIndisponivel):
    return JSONResponse(
        status_code=503,
        content={"detail": {
            "erro": "servico_indisponivel",
            "servico": exc.servico,
            "mensagem": f"O serviço de {NOMES_LEGIVEIS.get(exc.servico, exc.servico)} está indisponível no momento. "
                        "Tente novamente em instantes.",
        }},
    )


@app.middleware("http")
async def rastreio(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
    request_id_ctx.set(rid)
    inicio = time.perf_counter()
    resposta = await call_next(request)
    resposta.headers["X-Request-ID"] = rid
    log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path,
             resposta.status_code, (time.perf_counter() - inicio) * 1000, rid)
    return resposta


@app.get("/health")
def health():
    with Session() as s:
        s.execute(text("SELECT 1"))
    return {"servico": NOME_SERVICO, "status": "ok"}


@app.get("/tarefas/estatisticas")
def estatisticas():
    with Session() as s:
        todas = s.query(Tarefa).all()
    por_status = Counter(t.status for t in todas)
    por_prioridade = Counter(t.prioridade for t in todas)
    hoje = date.today()
    atrasadas = sum(1 for t in todas if t.prazo and t.prazo < hoje and t.status != "concluida")
    total = len(todas)
    return {
        "total": total,
        "por_status": {k: por_status.get(k, 0) for k in STATUS},
        "por_prioridade": {k: por_prioridade.get(k, 0) for k in PRIORIDADES},
        "por_projeto": dict(Counter(t.projeto_id for t in todas if t.projeto_id is not None)),
        "por_responsavel": dict(Counter(t.responsavel_id for t in todas if t.responsavel_id is not None)),
        "atrasadas": atrasadas,
        "percentual_concluido": round(100 * por_status.get("concluida", 0) / total) if total else 0,
    }


@app.get("/tarefas")
def listar(
    resposta: Response,
    status: str | None = None,
    prioridade: str | None = None,
    projeto_id: int | None = None,
    responsavel_id: int | None = None,
    q: str | None = None,
):
    with Session() as s:
        consulta = s.query(Tarefa)
        if status:
            consulta = consulta.filter(Tarefa.status == status)
        if prioridade:
            consulta = consulta.filter(Tarefa.prioridade == prioridade)
        if projeto_id is not None:
            consulta = consulta.filter(Tarefa.projeto_id == projeto_id)
        if responsavel_id is not None:
            consulta = consulta.filter(Tarefa.responsavel_id == responsavel_id)
        if q:
            consulta = consulta.filter(Tarefa.titulo.ilike(f"%{q}%"))
        tarefas = consulta.order_by(Tarefa.id).all()
    return enriquecer(tarefas, resposta)


@app.get("/tarefas/{id}")
def obter(id: int, resposta: Response):
    with Session() as s:
        t = s.get(Tarefa, id)
        if not t:
            raise HTTPException(404, "Tarefa não encontrada")
        return enriquecer([t], resposta)[0]


@app.post("/tarefas", status_code=201)
def criar(corpo: TarefaIn, resposta: Response):
    validar_referencias(corpo.responsavel_id, corpo.projeto_id)
    with Session() as s:
        t = Tarefa(**corpo.model_dump())
        if t.status == "concluida":
            t.concluida_em = datetime.now(timezone.utc)
        s.add(t)
        s.commit()
        s.refresh(t)
        log.info("EVENTO tarefa.criada id=%s status=%s", t.id, t.status)
        return enriquecer([t], resposta)[0]


def aplicar(id: int, campos: dict, resposta: Response) -> dict:
    """Atualiza os campos informados, validando referências e registrando mudanças de estado."""
    validar_referencias(campos.get("responsavel_id"), campos.get("projeto_id"))
    with Session() as s:
        t = s.get(Tarefa, id)
        if not t:
            raise HTTPException(404, "Tarefa não encontrada")
        status_anterior = t.status
        for campo, valor in campos.items():
            setattr(t, campo, valor)
        if t.status != status_anterior:
            t.concluida_em = datetime.now(timezone.utc) if t.status == "concluida" else None
            log.info("EVENTO tarefa.status_alterado id=%s de=%s para=%s", t.id, status_anterior, t.status)
        s.commit()
        s.refresh(t)
        return enriquecer([t], resposta)[0]


@app.put("/tarefas/{id}")
def atualizar(id: int, corpo: TarefaIn, resposta: Response):
    return aplicar(id, corpo.model_dump(), resposta)


@app.patch("/tarefas/{id}")
def atualizar_parcial(id: int, corpo: TarefaPatch, resposta: Response):
    campos = corpo.model_dump(exclude_unset=True)
    for obrigatorio in ("titulo", "status", "prioridade"):
        if obrigatorio in campos and campos[obrigatorio] is None:
            raise HTTPException(422, f"O campo '{obrigatorio}' não pode ser vazio")
    return aplicar(id, campos, resposta)


@app.delete("/tarefas/{id}", status_code=204)
def deletar(id: int):
    with Session() as s:
        t = s.get(Tarefa, id)
        if not t:
            raise HTTPException(404, "Tarefa não encontrada")
        s.delete(t)
        s.commit()
        log.info("EVENTO tarefa.removida id=%s", id)
