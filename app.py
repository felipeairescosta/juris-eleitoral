"""
App de consulta de jurisprudência eleitoral
Busca com BM25 — sem dependências de GPU ou disco persistente.
Uso: python app.py  →  http://localhost:5000
"""

import json
import re
import logging
import os
from pathlib import Path

from flask import Flask, render_template, request, jsonify
from rank_bm25 import BM25Okapi

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

_MERGED = Path("output/jurisprudencia_merged.json")
_TRECE  = Path("output/jurisprudencia.json")
DADOS_JSON = _MERGED if _MERGED.exists() else _TRECE

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Carga e indexação BM25 (executada uma única vez na inicialização)
# ---------------------------------------------------------------------------

log.info("Carregando dados...")
with open(DADOS_JSON, encoding="utf-8") as f:
    raw = json.load(f)

# Trunca resumo para reduzir uso de memória (512MB no plano gratuito do Render)
_decisoes: list[dict] = []
for d in raw:
    d["resumo"] = (d.get("resumo") or "")[:800]
    _decisoes.append(d)
del raw
log.info(f"{len(_decisoes)} decisoes carregadas.")


def _tokenizar(texto: str) -> list[str]:
    """Tokenização simples para português: minúsculas, remove pontuação."""
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", " ", texto)
    return [t for t in texto.split() if len(t) > 2]


log.info("Construindo índice BM25...")
_corpus_tokens: list[list[str]] = []
for d in _decisoes:
    campos = " ".join(filter(None, [
        d.get("titulo", ""),
        d.get("resumo", ""),
        d.get("subtopico", ""),
        d.get("topico", ""),
        d.get("numero_processo", ""),
    ]))
    _corpus_tokens.append(_tokenizar(campos))

_bm25 = BM25Okapi(_corpus_tokens)
del _corpus_tokens  # libera memória após indexação
log.info("Índice BM25 pronto.")

# Índices para filtros
_fontes   = sorted({d.get("fonte", "") for d in _decisoes if d.get("fonte")})
_topicos  = sorted({d.get("topico", "") for d in _decisoes if d.get("topico")})
_subtopicos: dict[str, list[str]] = {}
for d in _decisoes:
    t, s = d.get("topico", ""), d.get("subtopico", "")
    if t and s:
        _subtopicos.setdefault(t, set()).add(s)
_subtopicos = {t: sorted(subs) for t, subs in _subtopicos.items()}


# ---------------------------------------------------------------------------
# Funções de busca
# ---------------------------------------------------------------------------

def destacar(texto: str, termos: list[str]) -> str:
    if not termos or not texto:
        return texto
    padrao = re.compile(
        r"(" + "|".join(re.escape(t) for t in termos if len(t) > 2) + r")",
        re.IGNORECASE,
    )
    return padrao.sub(r"<mark>\1</mark>", texto)


def busca_bm25(query: str, topico: str, subtopico: str, fonte: str, n: int = 20) -> list[dict]:
    tokens = _tokenizar(query)
    scores = _bm25.get_scores(tokens)

    # Aplica filtros e coleta resultados ordenados por score
    resultados = []
    for i, score in enumerate(scores):
        if score <= 0:
            continue
        d = _decisoes[i]
        if topico    and d.get("topico")    != topico:
            continue
        if subtopico and d.get("subtopico") != subtopico:
            continue
        if fonte     and d.get("fonte")     != fonte:
            continue
        resultados.append((score, i))

    resultados.sort(reverse=True)
    resultados = resultados[:n]

    saida = []
    for score, i in resultados:
        d = _decisoes[i]
        saida.append({
            "fonte":           d.get("fonte", ""),
            "topico":          d.get("topico", ""),
            "subtopico":       d.get("subtopico", ""),
            "titulo":          d.get("titulo", ""),
            "numero_processo": d.get("numero_processo", ""),
            "data":            d.get("data", ""),
            "relator":         d.get("relator", ""),
            "tribunal":        d.get("tribunal", ""),
            "url_pdf":         d.get("url_pdf", ""),
            "url_fonte":       d.get("url_fonte", ""),
            "resumo":          d.get("resumo", "")[:2000],
            "score":           round(score, 1),
        })
    return saida


def busca_por_filtro(topico: str, subtopico: str, fonte: str) -> list[dict]:
    result = []
    for d in _decisoes:
        if topico    and d.get("topico")    != topico:    continue
        if subtopico and d.get("subtopico") != subtopico: continue
        if fonte     and d.get("fonte")     != fonte:     continue
        result.append({
            "fonte":           d.get("fonte", ""),
            "topico":          d.get("topico", ""),
            "subtopico":       d.get("subtopico", ""),
            "titulo":          d.get("titulo", ""),
            "numero_processo": d.get("numero_processo", ""),
            "data":            d.get("data", ""),
            "relator":         d.get("relator", ""),
            "tribunal":        d.get("tribunal", ""),
            "url_pdf":         d.get("url_pdf", ""),
            "url_fonte":       d.get("url_fonte", ""),
            "resumo":          d.get("resumo", "")[:2000],
            "score":           None,
        })
    return result[:200]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

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
    query    = request.args.get("q", "").strip()
    topico   = request.args.get("topico", "").strip()
    subtopico = request.args.get("subtopico", "").strip()
    fonte    = request.args.get("fonte", "").strip()

    if not query and not topico and not subtopico and not fonte:
        return jsonify({"resultados": [], "total": 0, "modo": "vazio"})

    if query:
        resultados = busca_bm25(query, topico, subtopico, fonte)
        modo = "bm25"
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
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Iniciando servidor na porta {port}")
    app.run(debug=False, host="0.0.0.0", port=port)
