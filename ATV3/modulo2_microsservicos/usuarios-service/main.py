"""Microsserviço de USUÁRIOS (responsáveis pelas tarefas).

Responsabilidade única: cadastro de pessoas. Não conhece tarefas nem projetos.
Banco próprio: schema "usuarios" (PostgreSQL) ou arquivo SQLite local.
"""
import logging
import os
import time
import uuid
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, MetaData, String, create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

NOME_SERVICO = "usuarios"
logging.basicConfig(level=logging.INFO, format="%(asctime)s [usuarios] %(message)s")
log = logging.getLogger(NOME_SERVICO)
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

# ----------------------------------------------------------------- banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./usuarios.db")
for prefixo in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(prefixo):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(prefixo):]
        break
EH_POSTGRES = DATABASE_URL.startswith("postgresql")
SCHEMA = os.getenv("DB_SCHEMA", "usuarios") if EH_POSTGRES else None

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


class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True)
    nome = Column(String, nullable=False)
    email = Column(String, nullable=False, unique=True)
    cargo = Column(String, default="Membro")


Base.metadata.create_all(engine)


# ----------------------------------------------------------------------- modelos
class UsuarioIn(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    cargo: str = Field(default="Membro", max_length=60)


def dados(u: Usuario) -> dict:
    return {"id": u.id, "nome": u.nome, "email": u.email, "cargo": u.cargo}


# --------------------------------------------------------------------------- app
app = FastAPI(title="Serviço de Usuários", version="2.0")


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


@app.get("/usuarios")
def listar(q: str | None = None):
    with Session() as s:
        consulta = s.query(Usuario)
        if q:
            consulta = consulta.filter(Usuario.nome.ilike(f"%{q}%"))
        return [dados(u) for u in consulta.order_by(Usuario.id)]


@app.get("/usuarios/{id}")
def obter(id: int):
    with Session() as s:
        u = s.get(Usuario, id)
        if not u:
            raise HTTPException(404, "Usuário não encontrado")
        return dados(u)


@app.post("/usuarios", status_code=201)
def criar(corpo: UsuarioIn):
    with Session() as s:
        u = Usuario(**corpo.model_dump())
        s.add(u)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(409, "Já existe um usuário com esse e-mail")
        s.refresh(u)
        return dados(u)


@app.put("/usuarios/{id}")
def atualizar(id: int, corpo: UsuarioIn):
    with Session() as s:
        u = s.get(Usuario, id)
        if not u:
            raise HTTPException(404, "Usuário não encontrado")
        u.nome, u.email, u.cargo = corpo.nome, corpo.email, corpo.cargo
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(409, "Já existe um usuário com esse e-mail")
        return dados(u)


@app.delete("/usuarios/{id}", status_code=204)
def deletar(id: int):
    with Session() as s:
        u = s.get(Usuario, id)
        if not u:
            raise HTTPException(404, "Usuário não encontrado")
        s.delete(u)
        s.commit()
