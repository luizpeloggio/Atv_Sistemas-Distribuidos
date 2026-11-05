"""API GATEWAY + painel web.

Ponto de entrada único do sistema. O navegador só conversa com o gateway:
  * serve o painel (static/index.html);
  * encaminha /api/usuarios, /api/projetos e /api/tarefas para o microsserviço certo;
  * /api/status  -> saúde e latência de cada serviço;
  * /api/resumo  -> indicadores agregados de vários serviços;
  * /api/demo    -> popula o sistema com dados de exemplo (via chamadas HTTP aos serviços).
"""
import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO, format="%(asctime)s [gateway] %(message)s")
log = logging.getLogger("gateway")

SERVICOS = {
    "usuarios": os.getenv("USUARIOS_URL", "http://localhost:8001").rstrip("/"),
    "projetos": os.getenv("PROJETOS_URL", "http://localhost:8002").rstrip("/"),
    "tarefas": os.getenv("TAREFAS_URL", "http://localhost:8003").rstrip("/"),
}
TIMEOUT = float(os.getenv("GATEWAY_TIMEOUT", "30"))
TIMEOUT_STATUS = float(os.getenv("STATUS_TIMEOUT", "12"))

cliente: httpx.AsyncClient


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    global cliente
    cliente = httpx.AsyncClient(timeout=TIMEOUT)
    yield
    await cliente.aclose()


app = FastAPI(title="Gateway", version="2.0", lifespan=ciclo_de_vida)


@app.middleware("http")
async def rastreio(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:8]
    request.state.rid = rid
    inicio = time.perf_counter()
    resposta = await call_next(request)
    resposta.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/api"):
        log.info("%s %s -> %s %.0fms rid=%s", request.method, request.url.path,
                 resposta.status_code, (time.perf_counter() - inicio) * 1000, rid)
    return resposta


NOMES_LEGIVEIS = {"usuarios": "usuários", "projetos": "projetos", "tarefas": "tarefas"}


def indisponivel(servico: str) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": {
        "erro": "servico_indisponivel",
        "servico": servico,
        "mensagem": f"O serviço de {NOMES_LEGIVEIS.get(servico, servico)} está indisponível no momento. Tente novamente em instantes.",
    }})


# ------------------------------------------------------------ status e indicadores
async def verificar(nome: str, base: str) -> dict:
    inicio = time.perf_counter()
    try:
        r = await cliente.get(f"{base}/health", timeout=TIMEOUT_STATUS)
        ok = r.status_code == 200
    except httpx.HTTPError:
        ok = False
    return {
        "servico": nome,
        "status": "online" if ok else "offline",
        "latencia_ms": round((time.perf_counter() - inicio) * 1000) if ok else None,
    }


@app.get("/api/health")
async def health():
    """Verificação leve (usada pelo Render); não depende dos outros serviços."""
    return {"servico": "gateway", "status": "ok"}


@app.get("/api/status")
async def status():
    servicos = await asyncio.gather(*(verificar(n, b) for n, b in SERVICOS.items()))
    return {"gateway": "online", "servicos": list(servicos)}


async def obter_json(url: str):
    try:
        r = await cliente.get(url)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


@app.get("/api/resumo")
async def resumo():
    tarefas, usuarios, projetos = await asyncio.gather(
        obter_json(f"{SERVICOS['tarefas']}/tarefas/estatisticas"),
        obter_json(f"{SERVICOS['usuarios']}/usuarios"),
        obter_json(f"{SERVICOS['projetos']}/projetos"),
    )
    return {
        "tarefas": tarefas,
        "usuarios": len(usuarios) if usuarios is not None else None,
        "projetos": len(projetos) if projetos is not None else None,
    }


# ----------------------------------------------------------------- dados de exemplo
@app.post("/api/demo")
async def demo(request: Request):
    cabecalho = {"X-Request-ID": request.state.rid}
    existentes = await asyncio.gather(
        obter_json(f"{SERVICOS['usuarios']}/usuarios"),
        obter_json(f"{SERVICOS['projetos']}/projetos"),
    )
    if existentes[0] is None:
        return indisponivel("usuarios")
    if existentes[1] is None:
        return indisponivel("projetos")
    if existentes[0] or existentes[1]:
        return {"criado": False, "mensagem": "O sistema já possui dados; nada foi criado."}

    async def criar(servico: str, corpo: dict) -> dict:
        r = await cliente.post(f"{SERVICOS[servico]}/{servico}", json=corpo, headers=cabecalho)
        r.raise_for_status()
        return r.json()

    hoje = date.today()
    try:
        usuarios = [
            await criar("usuarios", u) for u in (
                {"nome": "Ana Souza", "email": "ana.souza@exemplo.com", "cargo": "Product Owner"},
                {"nome": "Bruno Lima", "email": "bruno.lima@exemplo.com", "cargo": "Desenvolvedor Back-end"},
                {"nome": "Carla Mendes", "email": "carla.mendes@exemplo.com", "cargo": "Designer UX"},
                {"nome": "Diego Alves", "email": "diego.alves@exemplo.com", "cargo": "Engenheiro DevOps"},
            )
        ]
        projetos = [
            await criar("projetos", p) for p in (
                {"nome": "Portal do Cliente", "descricao": "Autoatendimento web para clientes.", "cor": "#6366f1"},
                {"nome": "App Mobile", "descricao": "Aplicativo para acompanhar pedidos.", "cor": "#06b6d4"},
                {"nome": "Migração para Nuvem", "descricao": "Mover a infraestrutura para a nuvem.", "cor": "#f59e0b"},
            )
        ]
        u, p = [x["id"] for x in usuarios], [x["id"] for x in projetos]
        dia = lambda n: (hoje + timedelta(days=n)).isoformat()  # noqa: E731
        tarefas = (
            ("Desenhar tela de login", "Protótipo de alta fidelidade.", "concluida", "media", u[2], p[0], dia(-3)),
            ("Criar API de autenticação", "JWT com refresh token.", "em_andamento", "alta", u[1], p[0], dia(2)),
            ("Definir backlog do MVP", "Priorizar histórias com o time.", "concluida", "alta", u[0], p[1], dia(-5)),
            ("Implementar lista de pedidos", "Tela com paginação.", "em_andamento", "media", u[1], p[1], dia(5)),
            ("Revisar identidade visual", "Cores, tipografia e ícones.", "pendente", "baixa", u[2], p[1], dia(9)),
            ("Configurar pipeline de deploy", "Build e deploy automáticos.", "em_andamento", "alta", u[3], p[2], dia(1)),
            ("Migrar banco para PostgreSQL", "Planejar janela de migração.", "pendente", "alta", u[3], p[2], dia(-1)),
            ("Escrever testes de integração", "Cobrir os fluxos principais.", "pendente", "media", u[1], p[0], dia(7)),
            ("Mapear custos na nuvem", "Estimativa mensal por serviço.", "pendente", "baixa", u[0], p[2], dia(12)),
            ("Entrevistar usuários", "Cinco entrevistas rápidas.", "concluida", "media", u[0], p[0], dia(-8)),
        )
        for titulo, descricao, st, prio, resp, proj, prazo in tarefas:
            await criar("tarefas", {
                "titulo": titulo, "descricao": descricao, "status": st, "prioridade": prio,
                "responsavel_id": resp, "projeto_id": proj, "prazo": prazo,
            })
    except httpx.HTTPError:
        return indisponivel("um dos serviços")
    return {"criado": True, "usuarios": len(usuarios), "projetos": len(projetos), "tarefas": len(tarefas)}


# ------------------------------------------------------------- encaminhamento (proxy)
@app.api_route("/api/{servico}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
@app.api_route("/api/{servico}/{caminho:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def encaminhar(servico: str, request: Request, caminho: str = ""):
    base = SERVICOS.get(servico)
    if base is None:
        return JSONResponse(status_code=404, content={"detail": f"Serviço '{servico}' não existe"})
    url = f"{base}/{servico}" + (f"/{caminho}" if caminho else "")
    cabecalhos = {"X-Request-ID": request.state.rid}
    if request.headers.get("content-type"):
        cabecalhos["Content-Type"] = request.headers["content-type"]
    try:
        r = await cliente.request(
            request.method, url, params=request.query_params,
            content=await request.body(), headers=cabecalhos,
        )
    except httpx.HTTPError:
        return indisponivel(servico)
    repassar = {k: v for k, v in r.headers.items() if k.lower() == "x-servicos-degradados"}
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"), headers=repassar)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="painel")
