"""
Raspador de Jurisprudência Eleitoral — TRE-CE
Coleta decisões organizadas por tópicos e subtópicos do site do TRE-CE.
Gera banco de dados em JSON e CSV.
"""

import re
import json
import csv
import time
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import urllib3
import requests
from bs4 import BeautifulSoup

# Certificados de tribunais brasileiros frequentemente não são reconhecidos
# pelo store padrão do Python. Desabilitamos a verificação apenas para este domínio.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

BASE_URL = "https://www.tre-ce.jus.br"
EMENTARIOS_URL = f"{BASE_URL}/jurisprudencia/ementarios-tematicos"
OUTPUT_DIR = Path("output")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Tópicos conhecidos (descobertos na exploração manual)
TOPICOS_CONHECIDOS = [
    {
        "titulo": "Prestação de Contas",
        "url": f"{BASE_URL}/jurisprudencia/prestacao-de-contas",
    },
    {
        "titulo": "Propaganda Eleitoral",
        "url": f"{BASE_URL}/jurisprudencia/propaganda-eleitoral",
    },
    {
        "titulo": "Registro de Candidaturas",
        "url": f"{BASE_URL}/jurisprudencia/arquivos-ementarios-tematicos/registro-de-candidaturas",
        "tipo": "pdf_direto",
    },
]


@dataclass
class Decisao:
    topico: str
    subtopico: str
    titulo: str
    numero_processo: str = ""
    data: str = ""
    relator: str = ""
    publicacao: str = ""
    tribunal: str = ""
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
    log.error(f"Falha ao buscar: {url}")
    return None


def extrair_topicos_da_pagina(soup: BeautifulSoup) -> list[dict]:
    """Descobre links de tópicos na página de ementários."""
    topicos = []
    for a in soup.select("a[href]"):
        href = a["href"]
        texto = a.get_text(strip=True)
        if not texto or len(texto) < 4:
            continue
        url_completa = urljoin(BASE_URL, href) if href.startswith("/") else href
        # Filtra links do domínio TRE-CE relacionados a jurisprudência
        if "tre-ce.jus.br/jurisprudencia" in url_completa and url_completa != EMENTARIOS_URL:
            topicos.append({"titulo": texto, "url": url_completa})
    return topicos


def detectar_tribunal(texto: str) -> str:
    texto_upper = texto.upper()
    if "TSE" in texto_upper:
        return "TSE"
    if "TRE-CE" in texto_upper or "TRE/CE" in texto_upper:
        return "TRE-CE"
    return "Desconhecido"


def extrair_numero_processo(texto: str) -> str:
    # Padrão: XXXXXXX-XX ou nº XXXXXXX-XX
    m = re.search(r"n[º°\.]?\s*([\d\.\-]+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Formato antigo sem hífen
    m = re.search(r"\b(\d{5,})\b", texto)
    if m:
        return m.group(1)
    return ""


def extrair_data(texto: str) -> str:
    # Padrões: DD/MM/AAAA, D.M.AAAA, DD.MM.AAAA
    m = re.search(r"\b(\d{1,2}[./]\d{1,2}[./]\d{4})\b", texto)
    if m:
        return m.group(1)
    # Formato por extenso: "mês de AAAA"
    m = re.search(
        r"\b(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})\b", texto, re.IGNORECASE
    )
    if m:
        return m.group(1)
    return ""


def extrair_relator(texto: str) -> str:
    # Formato "rel. Min. Fulano" ou "rel. Des. Fulano" ou "Relator: Fulano"
    m = re.search(
        r"(?:rel(?:ator[a]?)?\.?\s+(?:para\s+o\s+ac[oó]rd[aã]o\s+)?)"
        r"(?:Min\.?|Des(?:a)?\.?|Ju[íi]z[a]?|Dr[a]?\.?)?\s*([A-ZÁÉÍÓÚÃÕÂÊÔÇ][^\n,;(]+)",
        texto,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip().rstrip(".")
    return ""


def extrair_publicacao(texto: str) -> str:
    m = re.search(r"Publicação[:\s]+([^\n]+)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return ""


def parsear_bloco_decisao(bloco_texto: str, url_pdf: str, topico: str, subtopico: str) -> Decisao:
    """Converte texto de um bloco de decisão em objeto Decisao."""
    linhas = [l.strip() for l in bloco_texto.splitlines() if l.strip()]
    titulo = linhas[0] if linhas else ""
    texto_completo = "\n".join(linhas)

    return Decisao(
        topico=topico,
        subtopico=subtopico,
        titulo=titulo,
        numero_processo=extrair_numero_processo(titulo),
        data=extrair_data(texto_completo),
        relator=extrair_relator(texto_completo),
        publicacao=extrair_publicacao(texto_completo),
        tribunal=detectar_tribunal(titulo),
        resumo=texto_completo,
        url_pdf=url_pdf,
    )


def encontrar_subtopicos(soup: BeautifulSoup) -> list[dict]:
    """
    Detecta cabeçalhos de subtópicos dentro de uma página de tópico.
    Retorna lista de {'subtopico': str, 'elemento': Tag}.
    """
    subtopicos = []
    # Cabeçalhos tipicamente em h2, h3, h4 ou strong dentro de div
    for tag in soup.find_all(["h2", "h3", "h4"]):
        texto = tag.get_text(strip=True)
        if texto and len(texto) > 2:
            subtopicos.append({"subtopico": texto, "elemento": tag})
    return subtopicos


def raspar_pagina_topico(
    session: requests.Session, topico: dict
) -> list[Decisao]:
    """Raspa todas as decisões de uma página de tópico."""
    url = topico["url"]
    titulo_topico = topico["titulo"]
    log.info(f"Raspando tópico: {titulo_topico} ({url})")

    # Tópico que é PDF direto — registra como entrada única
    if topico.get("tipo") == "pdf_direto":
        return [
            Decisao(
                topico=titulo_topico,
                subtopico="(documento PDF completo)",
                titulo=titulo_topico,
                url_pdf=url,
                url_fonte=url,
            )
        ]

    soup = fetch(session, url)
    if not soup:
        return []

    decisoes: list[Decisao] = []
    subtopico_atual = "Geral"

    # Itera pelos elementos do conteúdo principal
    conteudo = soup.select_one("main, #content-core, .documentContent, article")
    if not conteudo:
        conteudo = soup

    elementos = conteudo.find_all(
        ["h1", "h2", "h3", "h4", "h5", "p", "li", "a"], recursive=True
    )

    bloco_atual: list[str] = []
    url_pdf_atual: str = ""

    def salvar_bloco():
        nonlocal bloco_atual, url_pdf_atual
        if bloco_atual and url_pdf_atual:
            d = parsear_bloco_decisao(
                "\n".join(bloco_atual), url_pdf_atual, titulo_topico, subtopico_atual
            )
            d.url_fonte = url
            decisoes.append(d)
        bloco_atual = []
        url_pdf_atual = ""

    for el in elementos:
        tag = el.name
        texto = el.get_text(strip=True)

        # Cabeçalho → novo subtópico
        if tag in ("h2", "h3", "h4", "h5") and texto:
            salvar_bloco()
            subtopico_atual = texto
            continue

        # Link para PDF de decisão
        if tag == "a":
            href = el.get("href", "")
            if "sjur-servicos.tse.jus.br" in href or "download/pdf" in href or "InteiroTeor" in href:
                salvar_bloco()
                url_pdf_atual = href if href.startswith("http") else urljoin(BASE_URL, href)
                # Texto do link como início do bloco
                if texto:
                    bloco_atual.append(texto)
            continue

        # Parágrafos e itens de lista com texto relevante
        if tag in ("p", "li") and texto and len(texto) > 10:
            bloco_atual.append(texto)

    salvar_bloco()

    # Estratégia alternativa: busca direta por todos os links PDF + contexto
    if not decisoes:
        log.info(f"  Estratégia alternativa para {titulo_topico}")
        for a in conteudo.find_all("a", href=True):
            href = a["href"]
            if "sjur-servicos" in href or "download/pdf" in href:
                url_pdf = href if href.startswith("http") else urljoin(BASE_URL, href)
                # Contexto: texto do elemento pai
                pai = a.find_parent(["li", "p", "div", "td"])
                contexto = pai.get_text(separator=" ", strip=True) if pai else a.get_text(strip=True)
                # Tenta deduzir subtópico a partir de cabeçalho anterior
                sub = subtopico_atual
                for anc in (a.find_previous(["h2", "h3", "h4", "h5"]),):
                    if anc:
                        sub = anc.get_text(strip=True)
                        break
                d = parsear_bloco_decisao(contexto, url_pdf, titulo_topico, sub)
                d.url_fonte = url
                decisoes.append(d)

    log.info(f"  → {len(decisoes)} decisões encontradas")
    return decisoes


def raspar_tudo(topicos: list[dict]) -> list[Decisao]:
    session = get_session()
    todas: list[Decisao] = []
    for topico in topicos:
        try:
            decisoes = raspar_pagina_topico(session, topico)
            todas.extend(decisoes)
        except Exception as e:
            log.error(f"Erro ao raspar {topico['titulo']}: {e}")
        time.sleep(1)  # pausa educada entre requisições
    return todas


def salvar_json(decisoes: list[Decisao], caminho: Path):
    dados = [asdict(d) for d in decisoes]
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    log.info(f"JSON salvo: {caminho} ({len(dados)} decisões)")


def salvar_csv(decisoes: list[Decisao], caminho: Path):
    if not decisoes:
        return
    campos = list(asdict(decisoes[0]).keys())
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for d in decisoes:
            writer.writerow(asdict(d))
    log.info(f"CSV salvo: {caminho} ({len(decisoes)} linhas)")


def gerar_relatorio(decisoes: list[Decisao], caminho: Path):
    """Gera relatório resumido em texto."""
    linhas = ["# Banco de Jurisprudência Eleitoral — TRE-CE\n"]
    linhas.append(f"Total de decisões: {len(decisoes)}\n")

    # Agrupa por tópico e subtópico
    grupos: dict[str, dict[str, list[Decisao]]] = {}
    for d in decisoes:
        grupos.setdefault(d.topico, {}).setdefault(d.subtopico, []).append(d)

    for topico, subtopicos in grupos.items():
        total_topico = sum(len(v) for v in subtopicos.values())
        linhas.append(f"\n## {topico} ({total_topico} decisões)\n")
        for sub, lista in subtopicos.items():
            linhas.append(f"\n### {sub} ({len(lista)} decisões)\n")
            for d in lista:
                linhas.append(f"- {d.titulo}")
                if d.data:
                    linhas.append(f"  Data: {d.data}")
                if d.relator:
                    linhas.append(f"  Relator: {d.relator}")
                if d.url_pdf:
                    linhas.append(f"  PDF: {d.url_pdf}")
                linhas.append("")

    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))
    log.info(f"Relatório salvo: {caminho}")


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    session = get_session()

    # Descobre tópicos dinamicamente na página principal
    log.info("Descobrindo tópicos na página de ementários...")
    soup = fetch(session, EMENTARIOS_URL)
    topicos_descobertos = []
    if soup:
        topicos_descobertos = extrair_topicos_da_pagina(soup)
        log.info(f"Tópicos descobertos: {[t['titulo'] for t in topicos_descobertos]}")

    # Combina tópicos descobertos com os conhecidos (sem duplicatas)
    # Filtra URLs irrelevantes (redes sociais, mailto, páginas de navegação)
    DOMINIOS_IGNORAR = {"facebook.com", "whatsapp.com", "instagram.com", "twitter.com"}
    SLUGS_IGNORAR = {
        "pesquisa-de-jurisprudencia", "jurisprudencia-por-assunto",
        "sumulas-do-tre-ce", "jurisprudencia",
    }
    urls_vistas = set()
    topicos_finais = []
    for t in TOPICOS_CONHECIDOS + topicos_descobertos:
        url = t["url"]
        if url.startswith("mailto:"):
            continue
        if any(d in url for d in DOMINIOS_IGNORAR):
            continue
        slug = url.rstrip("/").split("/")[-1]
        if slug in SLUGS_IGNORAR:
            continue
        if url not in urls_vistas:
            urls_vistas.add(url)
            topicos_finais.append(t)

    log.info(f"Total de tópicos a raspar: {len(topicos_finais)}")

    # Raspagem
    decisoes = raspar_tudo(topicos_finais)

    if not decisoes:
        log.warning("Nenhuma decisão encontrada. Verifique a estrutura do site.")
        return

    # Salva saídas
    salvar_json(decisoes, OUTPUT_DIR / "jurisprudencia.json")
    salvar_csv(decisoes, OUTPUT_DIR / "jurisprudencia.csv")
    gerar_relatorio(decisoes, OUTPUT_DIR / "relatorio.md")

    print(f"\nOK: {len(decisoes)} decisoes coletadas e salvas em '{OUTPUT_DIR}/'")
    print("  - jurisprudencia.json")
    print("  - jurisprudencia.csv")
    print("  - relatorio.md")


if __name__ == "__main__":
    main()
