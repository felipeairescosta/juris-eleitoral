"""
Scraper TSE v2 — estratégia "link-primeiro"
Garante captura de TODOS os PDFs independente da estrutura HTML da página.
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
from bs4 import BeautifulSoup, Tag, NavigableString

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

PDF_DOMINIOS = (
    "sjur-servicos.tse.jus.br",
    "download/pdf",
    "inter03.tse.jus.br",
    "tsevm",
    "/@@download",
)

IGNORAR_SLUGS = {
    "temas-selecionados", "@@search", "mapadacoletanea",
    "pesquisa", "busca", "acessibilidade", "mapa-do-site",
}


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
            log.warning(f"Tentativa {i+1}/{tentativas}: {e}")
            time.sleep(2 ** i)
    return None


def eh_pdf(href: str) -> bool:
    return any(p in href for p in PDF_DOMINIOS)


def normalizar_url(href: str) -> str:
    return href if href.startswith("http") else urljoin(BASE_URL, href)


def extrair_numero(texto: str) -> str:
    m = re.search(r"n[º°\.]?\s*([\d\.\-]+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\b(\d{5,})\b", texto)
    return m.group(1) if m else ""


def extrair_data(texto: str) -> str:
    m = re.search(r"(?:Ac\.\s+(?:de\s+)?)(\d{1,2}[./]\d{1,2}[./]\d{2,4})", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b", texto)
    return m.group(1) if m else ""


def extrair_relator(texto: str) -> str:
    m = re.search(
        r"(?:rel(?:ator[a]?)?\.?\s*)(?:Min(?:istr[ao])?\.?|Des(?:a)?\.?|Ju[íi]z[a]?)?\s*"
        r"([A-ZÁÉÍÓÚÃÕÂÊÔÇ][A-Za-záéíóúãõâêôçÁÉÍÓÚÃÕÂÊÔÇ\s]+?)(?:\s*[,;()\n]|$)",
        texto, re.IGNORECASE,
    )
    return m.group(1).strip().rstrip(".") if m else ""


def subtopico_anterior(elemento: Tag) -> str:
    """Encontra o cabeçalho (h2-h5) mais próximo antes do elemento."""
    for cab in elemento.find_all_previous(["h2", "h3", "h4", "h5"]):
        texto = cab.get_text(strip=True)
        if texto:
            return texto
    return "Generalidades"


def contexto_pai(elemento: Tag, max_chars: int = 8000) -> str:
    """Extrai ementa + citação do link de PDF.

    Estrutura TSE:
      <div class='conteudo_subtitulo'>
        <p>[ementa texto]</p>
        <p><em>(Ac. de ... <a href=pdf>)</em></p>   ← link pode estar aqui
        <p>(Ac. de ... <a href=pdf>)</p>             ← ou aqui
      </div>

    Estratégia: sobe até o <p> que contém o link (citação),
    depois coleta os <p> irmãos anteriores (ementa) até bater em
    outra citação ou heading.
    """
    from bs4 import NavigableString

    RE_CIT = re.compile(r"\(Ac\b|\bAcórdão\b|julgamento em", re.IGNORECASE)

    # 1. Encontra o <p> ancestral da citação (o <p> dentro do conteudo_subtitulo)
    cit_p = elemento.find_parent("p")
    if not cit_p:
        # sem <p> pai — usa fallback genérico
        for tag in ["li", "div"]:
            for pai in elemento.find_parents(tag):
                t = pai.get_text(" ", strip=True)
                if 20 < len(t) <= max_chars:
                    return t
        return elemento.get_text(strip=True)[:max_chars]

    # 2. Coleta <p> irmãos anteriores (ementa) até outra citação ou heading
    partes = []
    for sib in reversed(list(cit_p.previous_siblings)):
        if isinstance(sib, NavigableString):
            t = sib.strip()
            if t:
                partes.append(t)
            continue
        if sib.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            break
        t = sib.get_text(" ", strip=True)
        if not t:
            continue
        if RE_CIT.search(t):
            break  # outra citação = outra decisão
        partes.append(t)

    partes.reverse()
    partes.append(cit_p.get_text(" ", strip=True))
    resultado = " ".join(partes)

    # 3. Se ficou muito curto (só citação), tenta o <li> pai inteiro
    if len(resultado) < 200:
        for li in elemento.find_parents("li"):
            t = li.get_text(" ", strip=True)
            if len(t) > 200:
                return t[:max_chars]

    return resultado[:max_chars]


def descobrir_topicos(session: requests.Session) -> list[dict]:
    soup = fetch(session, INDEX_URL)
    if not soup:
        return []

    vistos: set[str] = set()
    topicos = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        texto = a.get_text(strip=True)
        if "/temas-selecionados/" not in href:
            continue
        if any(x in href for x in ["@@", ".pdf", "@@search"]):
            continue
        slug = href.rstrip("/").split("/")[-1]
        if slug in IGNORAR_SLUGS or not slug:
            continue
        url = normalizar_url(href)
        if url == INDEX_URL or url in vistos or len(texto) < 3:
            continue
        vistos.add(url)
        topicos.append({"titulo": texto, "url": url})

    log.info(f"Tópicos: {len(topicos)}")
    return topicos


def raspar_topico(session: requests.Session, topico: dict) -> list[Decisao]:
    """
    Estratégia link-primeiro: encontra TODOS os links PDF na página,
    depois extrai contexto e subtópico para cada um.
    Elimina duplicatas por URL de PDF.
    """
    url = topico["url"]
    titulo = topico["titulo"]

    soup = fetch(session, url)
    if not soup:
        return []

    conteudo = soup.select_one(
        "main, #content-core, .documentContent, article, .container-fluid"
    ) or soup

    vistos: set[str] = set()
    decisoes: list[Decisao] = []

    for a in conteudo.find_all("a", href=True):
        href = a["href"]
        if not eh_pdf(href):
            continue

        url_pdf = normalizar_url(href)
        if url_pdf in vistos:
            continue
        vistos.add(url_pdf)

        sub = subtopico_anterior(a)
        ctx = contexto_pai(a)
        texto_link = a.get_text(strip=True)

        # Título: texto do link se informativo, senão primeira linha do contexto
        titulo_dec = texto_link if len(texto_link) > 15 else ctx.split("\n")[0][:300]

        d = Decisao(
            fonte=FONTE,
            topico=titulo,
            subtopico=sub,
            titulo=titulo_dec[:300],
            numero_processo=extrair_numero(titulo_dec),
            data=extrair_data(ctx),
            relator=extrair_relator(ctx),
            tribunal="TSE",
            resumo=ctx[:8000],
            url_pdf=url_pdf,
            url_fonte=url,
        )
        decisoes.append(d)

    log.info(f"  {titulo}: {len(decisoes)} decisões")
    return decisoes


def main():
    OUTPUT_JSON.parent.mkdir(exist_ok=True)
    session = get_session()

    topicos = descobrir_topicos(session)
    if not topicos:
        log.error("Nenhum tópico encontrado.")
        return

    todas: list[Decisao] = []
    for topico in topicos:
        try:
            decisoes = raspar_topico(session, topico)
            todas.extend(decisoes)
        except Exception as e:
            log.error(f"Erro em '{topico['titulo']}': {e}")
        time.sleep(0.8)

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump([asdict(d) for d in todas], f, ensure_ascii=False, indent=2)

    por_topico: dict[str, int] = {}
    for d in todas:
        por_topico[d.topico] = por_topico.get(d.topico, 0) + 1

    print("\nDecisoes por topico (TSE v2):")
    for t, n in sorted(por_topico.items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {t}")
    print(f"\nTotal: {len(todas)} -> {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
