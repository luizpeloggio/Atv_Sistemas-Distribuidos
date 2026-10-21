import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# A URL do banco vem de variavel de ambiente (configurada no painel do Render).
DATABASE_URL = os.environ["DATABASE_URL"]
# O Render fornece "postgresql://..."; o SQLAlchemy precisa saber o driver (psycopg 3).
for prefixo in ("postgres://", "postgresql://"):
    if DATABASE_URL.startswith(prefixo):
        DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len(prefixo):]
        break

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
Base = declarative_base()


class Tarefa(Base):
    __tablename__ = "tarefas"
    id = Column(Integer, primary_key=True)
    titulo = Column(String, nullable=False)
    status = Column(String, default="pendente")
    responsavel = Column(String)


Base.metadata.create_all(engine)


class TarefaIn(BaseModel):
    titulo: str
    status: str = "pendente"
    responsavel: str | None = None


def dados(t):
    return {"id": t.id, "titulo": t.titulo, "status": t.status, "responsavel": t.responsavel}


app = FastAPI(title="Gerenciador de Tarefas")


@app.get("/")
def raiz():
    return {"servico": "Gerenciador de Tarefas", "docs": "/docs", "tarefas": "/tarefas"}


@app.post("/tarefas", status_code=201)
def criar(corpo: TarefaIn):
    with Session() as s:
        t = Tarefa(**corpo.model_dump())
        s.add(t)
        s.commit()
        s.refresh(t)
        return dados(t)


@app.get("/tarefas")
def listar():
    with Session() as s:
        return [dados(t) for t in s.query(Tarefa).order_by(Tarefa.id)]


@app.put("/tarefas/{id}")
def atualizar(id: int, corpo: TarefaIn):
    with Session() as s:
        t = s.get(Tarefa, id)
        if not t:
            raise HTTPException(404, "Tarefa nao encontrada")
        t.titulo, t.status, t.responsavel = corpo.titulo, corpo.status, corpo.responsavel
        s.commit()
        return dados(t)


@app.delete("/tarefas/{id}", status_code=204)
def deletar(id: int):
    with Session() as s:
        t = s.get(Tarefa, id)
        if not t:
            raise HTTPException(404, "Tarefa nao encontrada")
        s.delete(t)
        s.commit()
