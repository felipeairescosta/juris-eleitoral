"""
Scraper TRE-SP — Temas Selecionados (PDFs)
Requer: pip install pdfplumber requests

Uso: python scraper_tresp.py
Saída: output/jurisprudencia_tresp.json
"""

import io
import json
import re
from pathlib import Path

import pdfplumber
import requests

OUTPUT = Path("output/jurisprudencia_tresp.json")
BASE   = "https://www.tre-sp.jus.br/jurisprudencia/arquivos-da-secao-de-jurisprudencia-sp/temas-selecionados"

PDFS = [
    ("Ação de Investigação Judicial Eleitoral",      f"{BASE}/tre-sp-aije-temas-selecionados-2022"),
    ("Ação de Impugnação de Mandato Eletivo",        f"{BASE}/tre-sp-aime-temas-selecionados-2022"),
    ("Direito de Resposta",                          f"{BASE}/tre-sp-direito-de-resposta-temas-selecionados-2022"),
    ("Pesquisa Eleitoral",                           f"{BASE}/tre-sp-pesquisa-eleitoral-temas-selecionados-2022"),
    ("Prestação de Contas de Eleição",               f"{BASE}/tre-sp-prestacao-de-contas-temas-selecionados-2022"),
    ("Prestação de Contas Anual de Partido",         f"{BASE}/tre-sp-prestacao-de-contas-anual-temas-selecionados"),
    ("Propaganda",                                   f"{BASE}/tre-sp-propaganda-temas-selecionados-2022"),
    ("Recurso contra Expedição de Diploma",          f"{BASE}/tre-sp-rced-temas-selecionados-2022"),
    ("Registro de Candidatos",                       f"{BASE}/tre-sp-registro-de-candidatura-temas-selecionados-2022"),
    ("Representação - Doação acima do Limite Legal", f"{BASE}/tre-sp-doacao-acima-do-limite-legal-temas-selecionados-2022"),
    ("Representação - art. 30-A",                    f"{BASE}/tre-sp-art-30-a-arrecadacao-e-gastos-irregulares-temas-selecionados-2022"),
    ("Captação Ilícita de Sufrágio",                 f"{BASE}/tre-sp-captacao-ilicita-de-sufragio-temas-selecionados-2022"),
]

# Detecta início de decisão: "TRE/XX – Processo n." ou "TSE – Processo n." ou "TSE- Processo n."
RE_DECISAO = re.compile(
    r"^((?:TRE/[A-Z]{2}|TSE)\s*[-–]\s*Processo\s+n[.\s]+\S)",
    re.MULTILINE,
)
# Extrai tribunal e número do processo
RE_TRIBUNAL = re.compile(r"^(TRE/[A-Z]{2}|TSE)\s*[-–]", re.IGNORECASE)
RE_NUMERO   = re.compile(
    r"Processo\s+n[.\s]+(\d{7}-\d{2}\.\d{4}\.\d\.\d{2,3}\.\d{4}|\d{4,7}[-./]\d{2,})",
    re.IGNORECASE,
)
RE_DATA     = re.compile(
    r"\(?(?:Ac[oó]rd[aã]o|Decis[aã]o\s+monocr[aá]tica)\s+de\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    re.IGNORECASE,
)
RE_RELATOR  = re.compile(
    r"[Rr]el(?:ator[a]?)?\.?\s+(?:Min\.?|Des\.?|Juiz[a]?\.?)?\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇ][A-Za-záéíóúâêîôûãõàçÁÉÍÓÚÂÊÎÔÛÃÕÀÇ\s\.]{5,60}?)(?:\s*[,\n\)]|$)"
)
# Heading numerado (tópico/subtópico): "2. LITISPENDÊNCIA" ou "2.1. Litispendência entre..."
RE_HEADING  = re.compile(
    r"^(\d+(?:\.\d+)*\.?)\s+([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇ][^\n]{3,})",
    re.MULTILINE,
)
# Linhas de rodapé/cabeçalho a ignorar
RE_LIXO     = re.compile(
    r"^\s*\d{1,3}\s*$"          # Número de página sozinho
    r"|Secretaria de Gest"
    r"|Coordenadoria de Gest"
    r"|Se[çc][aã]o de Jurisprud"
    r"|Atualiza[çc][aã]o em"
    r"|APRESENTA[ÇC][AÃ]O"
    r"|SUM[ÁA]RIO"
    r"|T S$|EMAS ELECIONADOS",
    re.IGNORECASE,
)


def baixar_pdf(url: str) -> bytes:
    r = requests.get(url, timeout=30, verify=False, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })
    r.raise_for_status()
    return r.content


def extrair_texto(pdf_bytes: bytes) -> str:
    """Extrai texto de todas as páginas (pula capa e apresentação)."""
    linhas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pg in pdf.pages[3:]:  # pula capa, apresentação e sumário
            txt = pg.extract_text() or ""
            for linha in txt.splitlines():
                if not RE_LIXO.match(linha.strip()):
                    linhas.append(linha)
    return "\n".join(linhas)


def classificar_heading(num: str, texto: str) -> tuple[str, str]:
    """Retorna (topico, subtopico) com base no número do heading."""
    partes = num.rstrip(".").split(".")
    if len(partes) == 1:
        return texto.strip(), ""
    else:
        return "", texto.strip()


def parsear_decisoes(texto: str, topico_pdf: str) -> list[dict]:
    """Divide o texto em decisões individuais e extrai campos."""
    decisoes = []
    topico_atual    = topico_pdf
    subtopico_atual = ""

    # Divide em blocos por início de decisão
    blocos = RE_DECISAO.split(texto)
    # blocos[0] = texto antes da primeira decisão (headings)
    # blocos[1,3,5,...] = primeira linha da decisão
    # blocos[2,4,6,...] = resto do bloco até a próxima decisão

    # Processa headings no bloco inicial
    for m in RE_HEADING.finditer(blocos[0]):
        num  = m.group(1)
        head = m.group(2).strip()
        partes = num.rstrip(".").split(".")
        if len(partes) == 1:
            topico_atual    = head
            subtopico_atual = ""
        else:
            subtopico_atual = head

    # Itera sobre os pares (primeira_linha, resto)
    i = 1
    while i < len(blocos) - 1:
        primeira = blocos[i]
        resto    = blocos[i + 1] if i + 1 < len(blocos) else ""
        i += 2

        # Atualiza tópico/subtópico com headings no bloco anterior
        for m in RE_HEADING.finditer(resto):
            num  = m.group(1)
            head = m.group(2).strip()
            partes = num.rstrip(".").split(".")
            # Só atualiza se vier DEPOIS do texto da decisão
            # (headings no início do resto são do próximo subtópico)

        bloco = (primeira + resto).strip()

        # Extrai campos
        m_trib = RE_TRIBUNAL.match(bloco)
        tribunal = m_trib.group(1).replace("/", "-") if m_trib else "TRE-SP"

        m_num = RE_NUMERO.search(bloco)
        numero = m_num.group(1).strip() if m_num else ""

        m_data = RE_DATA.search(bloco)
        data = m_data.group(1).replace(".", "/") if m_data else ""

        m_rel = RE_RELATOR.search(bloco)
        relator = m_rel.group(1).strip()[:70] if m_rel else ""

        # Título = primeira linha significativa
        titulo = bloco.splitlines()[0].strip()[:300]

        decisoes.append({
            "topico":           topico_atual,
            "subtopico":        subtopico_atual,
            "titulo":           titulo,
            "numero_processo":  numero,
            "data":             data,
            "relator":          relator,
            "publicacao":       "",
            "tribunal":         tribunal,
            "resumo":           bloco[:3000],
            "url_pdf":          "",
            "url_fonte":        "",
            "fonte":            "TRE-SP - Temas Selecionados",
        })

        # Atualiza tópico com headings encontrados no resto
        for m in RE_HEADING.finditer(resto):
            num  = m.group(1)
            head = m.group(2).strip()
            # Verifica se o heading vem depois do texto da decisão (após o último "Acórdão de")
            pos_heading = m.start()
            m_last_ac = list(RE_DATA.finditer(resto))
            pos_acordao = m_last_ac[-1].end() if m_last_ac else 0
            if pos_heading > pos_acordao:
                partes = num.rstrip(".").split(".")
                if len(partes) == 1:
                    topico_atual    = head
                    subtopico_atual = ""
                else:
                    subtopico_atual = head

    return decisoes


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    todas = []

    for topico, url in PDFS:
        print(f"[{topico}]", end=" ", flush=True)
        try:
            pdf_bytes = baixar_pdf(url)
            texto     = extrair_texto(pdf_bytes)
            decisoes  = parsear_decisoes(texto, topico)
            print(f"{len(decisoes)} decisoes")
            todas.extend(decisoes)
        except Exception as e:
            print(f"ERRO: {e}")

    OUTPUT.write_text(
        json.dumps(todas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nTotal: {len(todas)} decisoes -> {OUTPUT}")


if __name__ == "__main__":
    main()
