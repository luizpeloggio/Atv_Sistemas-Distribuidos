"""Microsserviço de PROJETOS (agrupam tarefas).

Responsabilidade única: cadastro de projetos. Não conhece tarefas nem usuários.
Banco próprio: schema "projetos" (PostgreSQL) ou arquivo SQLite local.
"""
import logging
import os
import time
import uuid
from contextvars import ContextVar
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, MetaData, String, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

NOME_SERVICO = "projetos"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [projetos] %(message)s")
log = logging.getLogger(NOME_SERVICO)
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# ----------------------------------------------------------------- banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./projetos.db")
for prefixo in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(prefixo):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(prefixo):]
        break
EH_POSTGRES = DATABASE_URL.startswith("postgresql")
SCHEMA = os.getenv("DB_SCHEMA", "projetos") if EH_POSTGRES else None

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


class Projeto(Base):
    __tablename__ = "projetos"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False, unique=True)
    descricao = Column(String, default="")
    cor = Column(String, default="#6366f1")
    status = Column(String, default="ativo")


Base.metadata.create_all(engine)


# ----------------------------------------------------------------------- modelos
class ProjetoIn(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    descricao: str = Field(default="", max_length=300)
    cor: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    status: Literal["ativo", "arquivado"] = "ativo"


def dados(p: Projeto) -> dict:
    return {"id": p.id, "nome": p.nome, "descricao": p.descricao, "cor": p.cor, "status": p.status}


# --------------------------------------------------------------------------- app
app = FastAPI(title="Serviço de Projetos", version="2.0")


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


@app.get("/projetos")
def listar(status: str | None = None):
    with Session() as s:
        consulta = s.query(Projeto)
        if status:
            consulta = consulta.filter(Projeto.status == status)
        return [dados(p) for p in consulta.order_by(Projeto.id)]


@app.get("/projetos/{id}")
def obter(id: int):
    with Session() as s:
        p = s.get(Projeto, id)
        if not p:
            raise HTTPException(404, "Projeto não encontrado")
        return dados(p)


@app.post("/projetos", status_code=201)
def criar(corpo: ProjetoIn):
    with Session() as s:
        p = Projeto(**corpo.model_dump())
        s.add(p)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(409, "Já existe um projeto com esse nome")
        s.refresh(p)
        return dados(p)


@app.put("/projetos/{id}")
def atualizar(id: int, corpo: ProjetoIn):
    with Session() as s:
        p = s.get(Projeto, id)
        if not p:
            raise HTTPException(404, "Projeto não encontrado")
        p.nome, p.descricao, p.cor, p.status = corpo.nome, corpo.descricao, corpo.cor, corpo.status
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(409, "Já existe um projeto com esse nome")
        return dados(p)


@app.delete("/projetos/{id}", status_code=204)
def deletar(id: int):
    with Session() as s:
        p = s.get(Projeto, id)
        if not p:
            raise HTTPException(404, "Projeto não encontrado")
        s.delete(p)
        s.commit()
