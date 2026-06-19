"""
App de consulta de jurisprudência eleitoral — TRE-CE
Uso: python app.py  →  acesse http://localhost:5000
"""

import json
import re
import logging
import os
import ssl
from pathlib import Path

os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
ssl._create_default_https_context = ssl._create_unverified_context  # noqa

import httpx as _httpx
_orig_client = _httpx.Client.__init__
def _patched_client(self, *a, **kw):
    kw["verify"] = False
    _orig_client(self, *a, **kw)
_httpx.Client.__init__ = _patched_client
_orig_async = _httpx.AsyncClient.__init__
def _patched_async(self, *a, **kw):
    kw["verify"] = False
    _orig_async(self, *a, **kw)
_httpx.AsyncClient.__init__ = _patched_async

import chromadb
from flask import Flask, render_template, request, jsonify
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

CHROMA_DIR = Path("output/chroma_db")
_MERGED = Path("output/jurisprudencia_merged.json")
_TRECE  = Path("output/jurisprudencia.json")
DADOS_JSON = _MERGED if _MERGED.exists() else _TRECE
COLECAO = "jurisprudencia"
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

app = Flask(__name__)

# --- Inicialização dos recursos (carregados uma única vez) ---

log.info("Carregando modelo de embeddings...")
_modelo = SentenceTransformer(MODELO)

log.info("Conectando ao ChromaDB...")
_cliente = chromadb.PersistentClient(path=str(CHROMA_DIR))
_colecao = _cliente.get_collection(COLECAO)

log.info("Carregando JSON...")
with open(DADOS_JSON, encoding="utf-8") as f:
    _decisoes = json.load(f)

# Índices para filtros
_fontes = sorted({d.get("fonte", "") for d in _decisoes if d.get("fonte")})
_topicos = sorted({d["topico"] for d in _decisoes if d.get("topico")})
_subtopicos: dict[str, list[str]] = {}
for d in _decisoes:
    t = d.get("topico", "")
    s = d.get("subtopico", "")
    if t and s:
        _subtopicos.setdefault(t, set()).add(s)
_subtopicos = {t: sorted(subs) for t, subs in _subtopicos.items()}


def destacar(texto: str, termos: list[str]) -> str:
    """Envolve os termos buscados em <mark> para realce visual."""
    if not termos or not texto:
        return texto
    padrao = re.compile(
        r"(" + "|".join(re.escape(t) for t in termos if len(t) > 2) + r")",
        re.IGNORECASE,
    )
    return padrao.sub(r"<mark>\1</mark>", texto)


def busca_semantica(query: str, topico: str, subtopico: str, fonte: str, n: int = 20) -> list[dict]:
    """Busca por similaridade semântica com filtros opcionais."""
    filtros = {}
    if topico:
        filtros["topico"] = topico
    if subtopico:
        filtros["subtopico"] = subtopico
    if fonte:
        filtros["fonte"] = fonte

    # ChromaDB exige $and quando há múltiplos filtros
    if len(filtros) > 1:
        where = {"$and": [{k: v} for k, v in filtros.items()]}
    elif filtros:
        where = filtros
    else:
        where = None

    kwargs = dict(
        query_embeddings=[_modelo.encode(query).tolist()],
        n_results=min(n, _colecao.count()),
        include=["metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where

    res = _colecao.query(**kwargs)
    resultados = []
    for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
        resultados.append({**meta, "score": round((1 - dist) * 100, 1)})
    return resultados


def busca_por_filtro(topico: str, subtopico: str, fonte: str) -> list[dict]:
    """Lista decisões por tópico/subtópico/fonte sem query semântica."""
    result = []
    for d in _decisoes:
        if topico and d.get("topico") != topico:
            continue
        if subtopico and d.get("subtopico") != subtopico:
            continue
        if fonte and d.get("fonte") != fonte:
            continue
        result.append({
            "fonte": d.get("fonte", ""),
            "topico": d.get("topico", ""),
            "subtopico": d.get("subtopico", ""),
            "titulo": d.get("titulo", ""),
            "numero_processo": d.get("numero_processo", ""),
            "data": d.get("data", ""),
            "relator": d.get("relator", ""),
            "tribunal": d.get("tribunal", ""),
            "url_pdf": d.get("url_pdf", ""),
            "url_fonte": d.get("url_fonte", ""),
            "resumo": d.get("resumo", "")[:2000],
            "score": None,
        })
    return result[:50]


# --- Rotas ---

@app.route("/")
def index():
    return render_template(
        "index.html",
        topicos=_topicos,
        subtopicos=_subtopicos,
        fontes=_fontes,
        total=len(_decisoes),
    )


@app.route("/subtopicos/<topico>")
def get_subtopicos(topico: str):
    return jsonify(_subtopicos.get(topico, []))


@app.route("/buscar")
def buscar():
    query = request.args.get("q", "").strip()
    topico = request.args.get("topico", "").strip()
    subtopico = request.args.get("subtopico", "").strip()
    fonte = request.args.get("fonte", "").strip()

    if not query and not topico and not subtopico and not fonte:
        return jsonify({"resultados": [], "total": 0, "modo": "vazio"})

    if query:
        resultados = busca_semantica(query, topico, subtopico, fonte)
        modo = "semantica"
        termos = query.split()
        for r in resultados:
            r["titulo_hl"] = destacar(r.get("titulo", ""), termos)
            r["resumo_hl"] = destacar(r.get("resumo", ""), termos)
    else:
        resultados = busca_por_filtro(topico, subtopico, fonte)
        modo = "filtro"
        for r in resultados:
            r["titulo_hl"] = r.get("titulo", "")
            r["resumo_hl"] = r.get("resumo", "")

    return jsonify({"resultados": resultados, "total": len(resultados), "modo": modo})


if __name__ == "__main__":
    log.info("Iniciando servidor em http://localhost:5000")
    app.run(debug=False, port=5000)
