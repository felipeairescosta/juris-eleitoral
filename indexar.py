"""
Indexador — roda uma vez para criar o banco vetorial.
Uso: python indexar.py
"""

import json
import logging
import os
import ssl
from pathlib import Path

# Certificados de tribunais/redes corporativas bloqueiam SSL do Python.
# Desabilitamos em todas as camadas usadas pelo huggingface_hub/httpx/requests.
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["HF_HUB_DISABLE_SSL_VERIFICATION"] = "1"
os.environ["HTTPX_VERIFY"] = "0"
ssl._create_default_https_context = ssl._create_unverified_context  # noqa

# httpx (usado internamente pelo huggingface_hub) ignora os env vars acima —
# precisamos monkey-patch para forçar verify=False em todos os clientes.
import httpx as _httpx
_orig_client_init = _httpx.Client.__init__
_orig_async_client_init = _httpx.AsyncClient.__init__

def _patched_client(self, *a, **kw):
    kw["verify"] = False
    _orig_client_init(self, *a, **kw)

def _patched_async_client(self, *a, **kw):
    kw["verify"] = False
    _orig_async_client_init(self, *a, **kw)

_httpx.Client.__init__ = _patched_client
_httpx.AsyncClient.__init__ = _patched_async_client

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# Usa o arquivo mesclado se existir, senão o do TRE-CE
_MERGED = Path("output/jurisprudencia_merged.json")
_TRECE  = Path("output/jurisprudencia.json")
DADOS_JSON = _MERGED if _MERGED.exists() else _TRECE
CHROMA_DIR = Path("output/chroma_db")
COLECAO = "jurisprudencia"
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BATCH = 64


def texto_para_indexar(d: dict) -> str:
    """Combina campos relevantes num único texto para embedding."""
    partes = [
        d.get("topico", ""),
        d.get("subtopico", ""),
        d.get("titulo", ""),
        d.get("relator", ""),
        # Usa só os primeiros 800 chars do resumo para não distorcer o embedding
        d.get("resumo", "")[:800],
    ]
    return " | ".join(p for p in partes if p)


def main():
    log.info("Carregando dados...")
    with open(DADOS_JSON, encoding="utf-8") as f:
        decisoes = json.load(f)
    log.info(f"{len(decisoes)} decisões encontradas")

    log.info(f"Carregando modelo: {MODELO}")
    modelo = SentenceTransformer(MODELO)

    log.info("Conectando ao ChromaDB...")
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    cliente = chromadb.PersistentClient(path=str(CHROMA_DIR))

    # Recria a coleção do zero se já existir
    try:
        cliente.delete_collection(COLECAO)
        log.info("Coleção anterior removida.")
    except Exception:
        pass

    colecao = cliente.create_collection(
        name=COLECAO,
        metadata={"hnsw:space": "cosine"},
    )

    textos = [texto_para_indexar(d) for d in decisoes]
    ids = [str(i) for i in range(len(decisoes))]

    metadados = []
    for d in decisoes:
        metadados.append({
            "fonte": d.get("fonte", ""),
            "topico": d.get("topico", ""),
            "subtopico": d.get("subtopico", ""),
            "titulo": d.get("titulo", "")[:300],
            "numero_processo": d.get("numero_processo", ""),
            "data": d.get("data", ""),
            "relator": d.get("relator", ""),
            "tribunal": d.get("tribunal", ""),
            "url_pdf": d.get("url_pdf", ""),
            "url_fonte": d.get("url_fonte", ""),
            "resumo": d.get("resumo", "")[:2000],
        })

    log.info("Gerando embeddings e indexando (pode levar alguns minutos)...")
    for inicio in range(0, len(textos), BATCH):
        fim = min(inicio + BATCH, len(textos))
        batch_textos = textos[inicio:fim]
        batch_ids = ids[inicio:fim]
        batch_meta = metadados[inicio:fim]

        embeddings = modelo.encode(batch_textos, show_progress_bar=False).tolist()
        colecao.add(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_textos,
            metadatas=batch_meta,
        )
        log.info(f"  {fim}/{len(textos)} indexados")

    log.info(f"Indexacao concluida! {colecao.count()} documentos no banco.")
    print("\nPronto. Agora rode: python app.py")


if __name__ == "__main__":
    main()
