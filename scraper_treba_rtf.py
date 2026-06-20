"""
Scraper TRE-BA - Coletaneas Tematicas de Jurisprudencia (RTF)
Arquivos: registro de candidatura e prestacao de contas
Saida: output/jurisprudencia_treba_coletaneas.json
"""

import json
import re
from pathlib import Path

OUTPUT = Path("output/jurisprudencia_treba_coletaneas.json")

FONTES = [
    {
        "path": r"C:\Users\leona\Downloads\TRE-BA-coletanea-de-registro-de-candidatura.rtf",
        "url_fonte": "https://www.tre-ba.jus.br/jurisprudencia/colecoes-tematicas-de-jurisprudencia",
        "fonte": "TRE-BA - Colet\xe2nea Registro de Candidatura",
    },
    {
        "path": r"C:\Users\leona\Downloads\TRE-BA-coletanea-de-prestacao-de-contas (2).rtf",
        "url_fonte": "https://www.tre-ba.jus.br/jurisprudencia/colecoes-tematicas-de-jurisprudencia",
        "fonte": "TRE-BA - Colet\xe2nea Presta\xe7\xe3o de Contas",
    },
]

# Regex para encontrar o bloco de julgamento (ancora da citacao)
# Variantes: "julgamento em 05/11/2020", "julgamento em 05 /11/2020"
RE_JULGAMENTO = re.compile(
    r"julgamento em\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})",
    re.IGNORECASE,
)

RE_RELATOR = re.compile(
    r"[Rr]elator(?:a|(?:\(a\)))?\s*(?:designad[ao]\s*)?:?\s*"
    r"([A-Z\xc1\xc9\xcd\xd3\xda\xc2\xca\xce\xd4\xdb\xc3\xd5\xc0\xc7\xc4\xcb\xcf\xd6\xdc][^,;)\n]{4,100}?)"
    r"(?:\s*[,;)]|\s*$)",
    re.IGNORECASE | re.DOTALL,
)

RE_NUMERO = re.compile(r"(\d[\d.\-/]{4,})")


def strip_rtf(path):
    raw = open(path, "rb").read().decode("latin-1")
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw)
    raw = re.sub(r"\{\\\*[^{}]*\}", "", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    raw = re.sub(r"[{}\\]", " ", raw)

    # Passa 1: normaliza linhas (sem filtrar curtas ainda)
    bruto = []
    for l in raw.splitlines():
        l = " ".join(l.split())
        if l:
            bruto.append(l)

    # Passa 2: rejunta palavras quebradas pelo RTF mid-word
    # Ex: "Condenaç" + "ão" -> "Condenação"
    # Regra: linha anterior termina em letra, linha atual comeca em letra minuscula
    # ou letra acentuada, OU ambas em maiusculas (word-wrap de caps)
    merged = []
    for l in bruto:
        if (merged and merged[-1] and l
                and merged[-1][-1].isalpha()
                and merged[-1][-1] not in ".!?):,;\""
                and l[0].isalpha()
                and (l[0].islower()
                     or (merged[-1][-1].isupper() and l[0].isupper()))):
            merged[-1] = merged[-1] + l
        else:
            merged.append(l)

    return [l for l in merged if len(l) > 5 and not all(c in ". ;*?~" for c in l)]


def eh_topico(s):
    """Linha curta de cabecalho de topico (sem numeros, sem verbos de citacao, sem pontuacao final)."""
    s = s.strip()
    if not s or len(s) < 4 or len(s) > 90:
        return False
    # Nao pode ter numero de processo
    if re.search(r"\d{4,}", s):
        return False
    # Nao pode ser linha de citacao/publicacao
    if re.search(
        r"julgamento|relator|publicad|ac\xf3rd\xe3o|DJe|sess\xe3o|HYPERLINK"
        r"|provimento|impugna|procedente|julgad|defere|indefere|mant\xe9m"
        r"|constitui|verifica|determina|reconhece|afast",
        s, re.I,
    ):
        return False
    # Nao pode ser linha de corpo (numerada 1. 2. 3.)
    if re.match(r"^\d+[\.\)]\s", s):
        return False
    # Nao termina com ponto ou ponto-final (topicos reais nao terminam assim)
    if s.endswith(".") or s.endswith(";") or s.endswith(","):
        return False
    # Nao pode comecar com artigo + minuscula (fragmento de frase)
    if re.match(r"^[Aa] [a-z\xe0-\xff]", s):
        return False
    letras = [c for c in s if c.isalpha()]
    if len(letras) < 4:
        return False
    maiusc = sum(1 for c in letras if c.isupper())
    return s[0].isupper() and (maiusc / len(letras)) < 0.85


def encontrar_inicio_conteudo(lines):
    """Pula metadados/TOC e retorna o indice da primeira linha de conteudo real."""
    # Ultima ocorrencia de "Sumario" (fim do TOC)
    sumario_idx = 0
    for i, l in enumerate(lines):
        if re.match(r"Sum[a\xe1]rio\s*$", l, re.I):
            sumario_idx = i

    # A primeira decisao comeca com um topico (heading curto) antes da ementa
    # Procura primeiro julgamento e volta ate o topico que o precede
    for i in range(sumario_idx, min(sumario_idx + 600, len(lines))):
        if RE_JULGAMENTO.search(lines[i]):
            # Caminha para tras em busca de topico (linha curta Title Case)
            for j in range(i - 1, max(sumario_idx, i - 80), -1):
                if eh_topico(lines[j]) and len(lines[j]) < 80:
                    return j
            # Nao encontrou topico: retorna a primeira linha caps (ementa)
            for j in range(i - 1, max(sumario_idx, i - 80), -1):
                if re.search(r"[A-Z]{5,}", lines[j]):
                    return j
            return sumario_idx + 1
    return sumario_idx + 1


def parse_rtf(path, url_fonte, fonte):
    print(f"  Lendo {Path(path).name}...", end=" ", flush=True)
    lines = strip_rtf(path)
    inicio = encontrar_inicio_conteudo(lines)
    texto = "\n".join(lines[inicio:])

    decisoes = []
    topico_atual = ""
    prev_end = 0

    for m_julg in RE_JULGAMENTO.finditer(texto):
        dia, mes, ano = m_julg.group(1), m_julg.group(2), m_julg.group(3)
        data = f"{dia.zfill(2)}/{mes.zfill(2)}/{ano}"

        # --- Encontra inicio da citacao ---
        # Procura "(" antes de julgamento (max 1500 chars antes)
        busca_antes = texto[max(0, m_julg.start() - 1500): m_julg.start()]
        pos_paren = busca_antes.rfind("(")
        if pos_paren >= 0:
            cit_start = max(0, m_julg.start() - 1500) + pos_paren
        else:
            # Sem paren: inicio da ultima linha antes de julgamento
            pos_nl = busca_antes.rfind("\n")
            cit_start = max(0, m_julg.start() - 1500) + pos_nl + 1

        # --- Encontra fim da citacao ---
        pos_close = texto.find(")", m_julg.end())
        if pos_close >= 0 and pos_close - m_julg.end() < 600:
            cit_end = pos_close + 1
        else:
            # Sem ): fim da linha apos julgamento
            pos_nl = texto.find("\n", m_julg.end())
            cit_end = pos_nl if pos_nl >= 0 else len(texto)

        citacao = texto[cit_start:cit_end]

        # --- Extrai relator ---
        m_rel = RE_RELATOR.search(citacao)
        relator = re.sub(r"\s+", " ", m_rel.group(1)).strip() if m_rel else ""

        # --- Extrai numero do processo ---
        m_num = RE_NUMERO.search(citacao)
        numero_raw = m_num.group(1) if m_num else ""

        # Tipo de processo (primeiras palavras da citacao antes do numero)
        tipo_raw = re.match(
            r"[\(\s]*([A-Z\xc1\xc9\xcd\xd3\xda][^\d\n(]{3,80}?)\s*[\d(]",
            citacao,
        )
        tipo = tipo_raw.group(1).strip().rstrip(",") if tipo_raw else ""
        numero_processo = (tipo + " " + numero_raw).strip()

        # --- Bloco de corpo (texto entre fim da citacao anterior e inicio desta) ---
        corpo_block = texto[prev_end:cit_start].strip()
        corpo_lines = [l.strip() for l in corpo_block.splitlines() if l.strip()]

        # Topico: primeira linha curta e em Title Case (heading de secao)
        ementa_inicio = 0
        for k, cl in enumerate(corpo_lines[:5]):
            if eh_topico(cl) and len(cl) < 70:
                topico_atual = cl
                ementa_inicio = k + 1
                break

        # Remove linhas de URLs
        corpo_lines = [
            l for l in corpo_lines[ementa_inicio:]
            if not re.match(r"https?://", l, re.I) and "HYPERLINK" not in l
        ]

        titulo = corpo_lines[0][:300] if corpo_lines else ""
        resumo = "\n".join(corpo_lines)[:3000]

        if not titulo:
            prev_end = cit_end
            continue

        decisoes.append({
            "topico": topico_atual,
            "subtopico": "",
            "titulo": titulo,
            "numero_processo": numero_processo,
            "data": data,
            "relator": relator,
            "tribunal": "TRE-BA",
            "resumo": resumo,
            "url_pdf": path,
            "url_fonte": url_fonte,
            "fonte": fonte,
        })

        prev_end = cit_end

    print(f"{len(decisoes)} decisoes")
    return decisoes


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    todas = []
    for info in FONTES:
        d = parse_rtf(info["path"], info["url_fonte"], info["fonte"])
        todas.extend(d)

    OUTPUT.write_text(json.dumps(todas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTotal: {len(todas)} decisoes -> {OUTPUT}")


if __name__ == "__main__":
    main()
