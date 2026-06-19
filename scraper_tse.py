"""
Raspador — TSE Temas Selecionados
https://temasselecionados.tse.jus.br/temas-selecionados
"""

import re
import json
import time
import logging
import ssl
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

ssl._create_default_https_context = ssl._create_unverified_context  # noqa
os.environ["REQUESTS_CA_BUNDLE"] = ""

import requests
from bs4 import BeautifulSoup, Tag

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://temasselecionados.tse.jus.br"
INDEX_URL = f"{BASE_URL}/temas-selecionados"
OUTPUT_JSON = Path("output/jurisprudencia_tse.json")
FONTE = "TSE - Temas Selecionados"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Padrões de URL de PDF de decisões
PDF_DOMINIOS = (
    "sjur-servicos.tse.jus.br",
    "download/pdf",
    "inter03.tse.jus.br",
    "tsevm",
    "/@@download",
)


@dataclass
class Decisao:
    fonte: str
    topico: str
    subtopico: str
    titulo: str
    numero_processo: str = ""
    data: str = ""
    relator: str = ""
    tribunal: str = "TSE"
    resumo: str = ""
    url_pdf: str = ""
    url_fonte: str = ""


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def fetch(session: requests.Session, url: str, tentativas: int = 3) -> Optional[BeautifulSoup]:
    for i in range(tentativas):
        try:
            r = session.get(url, timeout=30, verify=False)
            r.raise_for_status()
            r.encoding = "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException as e:
            log.warning(f"Tentativa {i+1}/{tentativas} falhou para {url}: {e}")
            time.sleep(2 ** i)
    log.error(f"Falha definitiva: {url}")
    return None


def descobrir_topicos(session: requests.Session) -> list[dict]:
    """Lê a página índice e extrai todos os tópicos com URLs."""
    soup = fetch(session, INDEX_URL)
    if not soup:
        return []

    topicos = []
    urls_vistas = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        texto = a.get_text(strip=True)

        # Filtra links de tópicos (slug após /temas-selecionados/)
        if "/temas-selecionados/" not in href:
            continue
        # Remove links genéricos (busca, downloads, etc.)
        if any(x in href for x in ["@@", ".pdf", "@@search", "mapadacoletanea"]):
            continue

        url = urljoin(BASE_URL, href) if not href.startswith("http") else href
        if url == INDEX_URL or url in urls_vistas:
            continue

        if texto and len(texto) > 3:
            urls_vistas.add(url)
            topicos.append({"titulo": texto, "url": url})

    log.info(f"Tópicos encontrados: {len(topicos)}")
    return topicos


def eh_url_pdf(href: str) -> bool:
    return any(p in href for p in PDF_DOMINIOS)


def extrair_numero(texto: str) -> str:
    m = re.search(r"n[º°\.]?\s*([\d\.\-]+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(\d{5,})\b", texto)
    return m.group(1) if m else ""


def extrair_data(texto: str) -> str:
    m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b", texto)
    if m:
        return m.group(1)
    m = re.search(r"Ac\.\s+de\s+(\d{1,2}/\d{1,2}/\d{4})", texto)
    if m:
        return m.group(1)
    return ""


def extrair_relator(texto: str) -> str:
    m = re.search(
        r"(?:rel(?:ator[a]?)?\.?\s*)(?:Min(?:istr[ao])?\.?|Des(?:a)?\.?|Ju[íi]z[a]?)?\s*"
        r"([A-ZÁÉÍÓÚÃÕÂÊÔÇ][A-Za-záéíóúãõâêôçÁÉÍÓÚÃÕÂÊÔÇ\s]+?)(?:\s*[,;()\n]|$)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().rstrip(".")
    return ""


def raspar_topico(session: requests.Session, topico: dict) -> list[Decisao]:
    """Raspa todas as decisões de uma página de tópico do TSE."""
    url = topico["url"]
    titulo_topico = topico["titulo"]
    log.info(f"Raspando: {titulo_topico}")

    soup = fetch(session, url)
    if not soup:
        return []

    decisoes: list[Decisao] = []
    subtopico_atual = "Generalidades"

    # Área de conteúdo principal
    conteudo = soup.select_one(
        "main, #content-core, .documentContent, article, .container-fluid"
    ) or soup

    # Percorre todos os elementos relevantes
    bloco: list[str] = []
    url_pdf_atual = ""

    def flush_bloco():
        nonlocal bloco, url_pdf_atual
        if not bloco:
            return
        texto = "\n".join(bloco).strip()
        if not texto:
            bloco = []
            url_pdf_atual = ""
            return

        titulo = bloco[0].strip() if bloco else ""
        d = Decisao(
            fonte=FONTE,
            topico=titulo_topico,
            subtopico=subtopico_atual,
            titulo=titulo[:300],
            numero_processo=extrair_numero(titulo),
            data=extrair_data(texto),
            relator=extrair_relator(texto),
            tribunal="TSE",
            resumo=texto[:3000],
            url_pdf=url_pdf_atual,
            url_fonte=url,
        )
        decisoes.append(d)
        bloco = []
        url_pdf_atual = ""

    for el in conteudo.descendants:
        if not isinstance(el, Tag):
            continue

        tag = el.name
        if tag not in ("h1", "h2", "h3", "h4", "h5", "p", "li", "a", "div"):
            continue

        # Não desce em elementos já processados pelos filhos diretos
        if tag == "div":
            continue

        texto = el.get_text(separator=" ", strip=True)
        if not texto:
            continue

        # Cabeçalhos → novo subtópico
        if tag in ("h2", "h3", "h4", "h5"):
            flush_bloco()
            subtopico_atual = texto
            continue

        # Links para PDF de decisão
        if tag == "a":
            href = el.get("href", "")
            if eh_url_pdf(href):
                flush_bloco()
                url_pdf_atual = href if href.startswith("http") else urljoin(BASE_URL, href)
                if texto:
                    bloco.append(texto)
            continue

        # Parágrafos e itens de lista com conteúdo
        if tag in ("p", "li") and len(texto) > 15:
            # Detecta se o parágrafo menciona um acórdão (novo bloco)
            if re.search(r"\bAc\.\s+de\b", texto, re.IGNORECASE) and bloco and not url_pdf_atual:
                flush_bloco()
            bloco.append(texto)

    flush_bloco()

    # Fallback: busca direta por todos os links PDF + contexto pai
    if not decisoes:
        log.info(f"  [fallback] buscando links PDF diretos em {titulo_topico}")
        subtopico_atual = "Generalidades"
        for a in conteudo.find_all("a", href=True):
            href = a["href"]
            if not eh_url_pdf(href):
                continue
            url_pdf = href if href.startswith("http") else urljoin(BASE_URL, href)
            # Contexto: texto do elemento pai mais próximo com conteúdo relevante
            pai = a.find_parent(["li", "p", "div", "td", "article"])
            contexto = pai.get_text(separator=" ", strip=True) if pai else a.get_text(strip=True)
            # Subtópico: cabeçalho anterior
            cab = a.find_previous(["h2", "h3", "h4", "h5"])
            sub = cab.get_text(strip=True) if cab else "Generalidades"
            d = Decisao(
                fonte=FONTE,
                topico=titulo_topico,
                subtopico=sub,
                titulo=contexto[:200],
                numero_processo=extrair_numero(contexto),
                data=extrair_data(contexto),
                relator=extrair_relator(contexto),
                tribunal="TSE",
                resumo=contexto[:3000],
                url_pdf=url_pdf,
                url_fonte=url,
            )
            decisoes.append(d)

    log.info(f"  → {len(decisoes)} decisões")
    return decisoes


def main():
    OUTPUT_JSON.parent.mkdir(exist_ok=True)
    session = get_session()

    topicos = descobrir_topicos(session)
    if not topicos:
        log.error("Nenhum tópico encontrado. Verifique a URL.")
        return

    todas: list[Decisao] = []
    for topico in topicos:
        try:
            decisoes = raspar_topico(session, topico)
            todas.extend(decisoes)
        except Exception as e:
            log.error(f"Erro em '{topico['titulo']}': {e}")
        time.sleep(1)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump([asdict(d) for d in todas], f, ensure_ascii=False, indent=2)

    log.info(f"Salvo: {OUTPUT_JSON} ({len(todas)} decisões)")

    # Estatísticas por tópico
    por_topico: dict[str, int] = {}
    for d in todas:
        por_topico[d.topico] = por_topico.get(d.topico, 0) + 1
    print("\nDecisoes por topico (TSE):")
    for t, n in sorted(por_topico.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {t}")
    print(f"\nTotal: {len(todas)} decisoes salvas em {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
