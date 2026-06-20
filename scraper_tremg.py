"""
Scraper TRE-MG - Ementario Tematico (PDFs anuais 2022-2025)
Requer: pip install pdfplumber requests

Uso: python scraper_tremg.py
Saida: output/jurisprudencia_tremg.json
"""

import io
import json
import re
from pathlib import Path

import pdfplumber
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

OUTPUT = Path("output/jurisprudencia_tremg.json")

BASE = "https://www.tre-mg.jus.br/jurisprudencia/copy_of_informativo-tre/arquivos-de-ementario-tematico"

# (ano, url_pdf, paginas_pular, url_fonte)
PDFS = [
    (
        "2025",
        BASE + "/tre-mg_ementario_anual_2025/@@display-file/file/TRE-MG_Ementario_2025.pdf",
        5,
        BASE + "/tre-mg_ementario_anual_2025",
    ),
    (
        "2024",
        BASE + "/tre-mg_ementario_2024/@@display-file/file/TRE-MG_ementario_2024_rev.pdf",
        5,
        BASE + "/tre-mg_ementario_2024",
    ),
    (
        "2023",
        BASE + "/tre-mg-ementario-2023/@@display-file/file/tre-mg-ementario-2023.pdf",
        6,
        BASE + "/tre-mg-ementario-2023",
    ),
    (
        "2022",
        BASE + "/tremg-ementario-2022/@@display-file/file/tre-mg-ementario-2022-b.pdf",
        5,
        BASE + "/tremg-ementario-2022",
    ),
]

# Linha de citacao que encerra cada decisao.
# Variantes encontradas nos 4 PDFs (2022-2025):
#   Ac. TRE-MG no RE n° NNN                    basico
#   Ac. TRE-MG, no RE n° NNN                   virgula antes de "no"
#   Ac. TRE-MG na RVC n° NNN                   "na" em vez de "no"
#   Ac. TRE-MG nos ED no RE n° NNN             "nos" + tipo composto
#   Ac. TRE-MG no AgR no(a) RE n° NNN          AgR com subtipo
#   Ac. TREMG no RE n° NNN                     sem hifen
#   Ac TREMG RE n° NNN                         sem ponto, sem "no"
#   Ac. TRE-MG no Agravo Regimental n° NNN     tipo por extenso
#   publicado no DJE de DD/MM/AAAA             DJE em vez de DJEMG
#   publicado em Sessao de DD/MM/AAAA          sessao em vez de diario
#   publicado no de DD/MM/AAAA                 sem veiculo
RE_CITACAO = re.compile(
    r"Ac\.?\s*"
    r"TRE[-\s]?MG"
    r"[,]?\s+"
    # tipo: palavra(s) simples OU "AgR no(a) RE" OU "ED nos ED no RE" OU "Agravo Regimental"
    # NAO usar [\s\w]* livre — causa backtracking catastrofico com (.*?)DOTALL
    r"(?:n[ao]s?\s+)?"
    r"("
        r"[\w.]+(?:\s+n[ao]s?\(?[a-z]?\)?\s+[\w.]+)*"  # RE / AgR no(a) RE / ED nos ED no RE
        r"|Agravo\s+Regimental"
    r")"
    r"\.?\s+[Nn][\xb0o\xba\.]\s*(\d[\d\.\-/]+)"  # [.] n°/N°/no NUMERO
    r"(.*?)"
    r"(?:publicado|Publicado)"
    r"\s+(?:"
        r"no\s+(?:DJEMG|DJE)[,]?\s+de"        # publicado no DJEMG[,] de ...
        r"|no\s+de"                             # publicado no de ...
        r"|em\s+[Ss]ess[a\xe3]o\s+(?:de|em)"  # publicado em Sessao de/em ...
    r")"
    r"\s*\d{1,2}[./]\d{1,2}[./]\d{4}\.?",
    re.IGNORECASE | re.DOTALL,
)
RE_DATA = re.compile(r"(\d{1,2}[./]\d{1,2}[./]\d{4})")
RE_REL = re.compile(
    r"Rel\.?\s+(?:Juiz[a]?\s+|Des\.?\s+|"
    r"Ju\xedza\s+|Min\.?\s+)?"
    r"([A-Z\xc1\xc9\xcd\xd3\xda\xc2\xca\xce\xd4\xdb\xc3\xd5\xc0\xc7]"
    r"[A-Za-z\xe1\xe9\xed\xf3\xfa\xe2\xea\xee\xf4\xfb\xe3\xf5\xe0\xe7"
    r"\xc1\xc9\xcd\xd3\xda\xc2\xca\xce\xd4\xdb\xc3\xd5\xc0\xc7\s\.]{4,80}?)"
    r"(?:,\s*publicado|\s*\.\s*$|\s*$)",
    re.IGNORECASE | re.DOTALL,
)

# Linhas de rodape/cabecalho para ignorar
RE_LIXO = re.compile(
    r"^\s*Sum[a\xe1]rio\s*$"
    r"|Ement[a\xe1]rio Tem[a\xe1]tico.*TRE-MG"
    r"|^\s*\d{1,3}\s*$"
    r"|\.{5,}"
    r"|TRIBUNAL REGIONAL ELEITORAL"
    r"|SECRETARIA DA PRESID"
    r"|COORDENADORIA DE SESS"
    r"|SE[C\xc7][A\xc3]O DE JURISPRUD",
    re.IGNORECASE,
)


def eh_topico(s):
    s = s.strip()
    if not s or len(s) < 4 or len(s) > 120:
        return False
    letras = [c for c in s if c.isalpha()]
    if len(letras) < 4:
        return False
    maiusc = sum(1 for c in letras if c.isupper())
    return (maiusc / len(letras)) >= 0.7


def eh_subtopico(s):
    s = s.strip()
    if not s or len(s) < 4 or len(s) > 120:
        return False
    if eh_topico(s):
        return False
    if re.search(r"Ac\.?\s*TRE", s, re.IGNORECASE):
        return False
    return s[0].isupper() and s[0] not in '"“«'


def baixar_pdf(url):
    r = requests.get(url, timeout=180, verify=False, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }, stream=True)
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(chunk_size=65536):
        chunks.append(chunk)
    return b"".join(chunks)


def extrair_texto(pdf_bytes, pular=5):
    linhas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for pg in pdf.pages[pular:]:
            txt = pg.extract_text() or ""
            for linha in txt.splitlines():
                s = linha.strip()
                if s and not RE_LIXO.search(s):
                    linhas.append(linha)
    return "\n".join(linhas)


# Estado mutavel compartilhado entre chamadas
_estado = {"topico": "", "subtopico": ""}


def parsear_decisoes(texto, url_pdf, url_fonte):
    decisoes = []
    _estado["topico"]    = ""
    _estado["subtopico"] = ""

    citacoes = list(RE_CITACAO.finditer(texto))
    if not citacoes:
        return []

    for i, m_cit in enumerate(citacoes):
        inicio_bloco = citacoes[i - 1].end() if i > 0 else 0
        bloco        = texto[inicio_bloco:m_cit.end()]

        # Cabecalho = parte antes das aspas de abertura (headings de topico)
        m_aspas = re.search(r'["“«]', bloco)
        cabecalho = bloco[:m_aspas.start()] if m_aspas else ""

        for linha in cabecalho.splitlines():
            s = linha.strip()
            if eh_topico(s):
                _estado["topico"]    = s
                _estado["subtopico"] = ""
            elif eh_subtopico(s):
                _estado["subtopico"] = s

        topico_atual    = _estado["topico"]
        subtopico_atual = _estado["subtopico"]

        # Corpo da decisao (entre aspas de abertura e inicio da citacao)
        corpo_inicio = bloco[m_aspas.start():] if m_aspas else bloco
        pos_cit_local = corpo_inicio.find(m_cit.group(0)[:40])
        if pos_cit_local > 0:
            corpo_raw = corpo_inicio[:pos_cit_local]
        else:
            corpo_raw = corpo_inicio[:m_cit.start() - inicio_bloco]

        corpo = corpo_raw.strip().lstrip('"“«').rstrip('"”»').strip()

        # Dados da citacao
        tipo_proc       = m_cit.group(1).upper()
        num_bruto       = m_cit.group(2).strip().rstrip(".,")
        numero_processo = (tipo_proc + " " + num_bruto).strip() if num_bruto else ""

        datas = RE_DATA.findall(m_cit.group(0))
        data  = datas[0] if datas else ""

        m_rel   = RE_REL.search(m_cit.group(0))
        relator = re.sub(r"\s+", " ", m_rel.group(1)).strip() if m_rel else ""

        titulo_lines = [l for l in corpo.splitlines() if l.strip()]
        titulo = titulo_lines[0].strip()[:300] if titulo_lines else ""

        decisoes.append({
            "topico":          topico_atual,
            "subtopico":       subtopico_atual,
            "titulo":          titulo,
            "numero_processo": numero_processo,
            "data":            data,
            "relator":         relator,
            "tribunal":        "TRE-MG",
            "resumo":          corpo[:3000],
            "url_pdf":         url_pdf,
            "url_fonte":       url_fonte,
            "fonte":           "TRE-MG - Ementario Tematico",
        })

    return decisoes


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    todas = []

    for ano, url, pular, url_fonte in PDFS:
        print("[" + ano + "] Baixando...", end=" ", flush=True)
        try:
            pdf_bytes = baixar_pdf(url)
            print(str(len(pdf_bytes) // 1024) + " KB -- extraindo...", end=" ", flush=True)
            texto    = extrair_texto(pdf_bytes, pular)
            decisoes = parsear_decisoes(texto, url, url_fonte)
            print(str(len(decisoes)) + " decisoes")
            todas.extend(decisoes)
        except Exception as e:
            print("ERRO: " + str(e))

    OUTPUT.write_text(
        json.dumps(todas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nTotal: " + str(len(todas)) + " decisoes -> " + str(OUTPUT))


if __name__ == "__main__":
    main()
