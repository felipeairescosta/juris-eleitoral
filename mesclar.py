"""
Mescla os JSONs do TRE-CE, TSE e TRE-RS num único arquivo consolidado.
Uso: python mesclar.py
"""

import json
from pathlib import Path

TRECE_JSON       = Path("output/jurisprudencia.json")
TSE_JSON         = Path("output/jurisprudencia_tse.json")
SUMULAS_JSON     = Path("output/jurisprudencia_sumulas_trece.json")
SUMULAS_TSE_JSON = Path("output/jurisprudencia_sumulas_tse.json")
TRERS_JSON       = Path("output/jurisprudencia_trers.json")
TRESP_JSON       = Path("output/jurisprudencia_tresp.json")
TREMG_JSON       = Path("output/jurisprudencia_tremg.json")
SUMULAS_TRERJ_JSON  = Path("output/jurisprudencia_sumulas_trerj.json")
SUMULAS_TREBA_JSON  = Path("output/jurisprudencia_sumulas_treba.json")
COLETANEAS_TREBA_JSON = Path("output/jurisprudencia_treba_coletaneas.json")
MERGED_JSON         = Path("output/jurisprudencia_merged.json")

FONTES = [
    (TRECE_JSON,           "TRE-CE - Ementários Temáticos"),
    (TSE_JSON,             "TSE - Temas Selecionados"),
    (SUMULAS_JSON,         "TRE-CE - Súmulas"),
    (SUMULAS_TSE_JSON,     "TSE - Súmulas"),
    (TRERS_JSON,           "TRE-RS - Ementário Temático"),
    (TRESP_JSON,           "TRE-SP - Temas Selecionados"),
    (TREMG_JSON,           "TRE-MG - Ementário Temático"),
    (SUMULAS_TRERJ_JSON,   "TRE-RJ - Súmulas"),
    (SUMULAS_TREBA_JSON,   "TRE-BA - Súmulas"),
    (COLETANEAS_TREBA_JSON, "TRE-BA - Coletâneas Temáticas"),
]


def normalizar(d: dict, fonte_padrao: str) -> dict:
    """Garante que todos os campos existam e adiciona 'fonte' se ausente."""
    campos = [
        "fonte", "topico", "subtopico", "titulo", "numero_processo",
        "data", "relator", "tribunal", "resumo", "url_pdf", "url_fonte",
    ]
    out = {c: d.get(c, "") for c in campos}
    if not out["fonte"]:
        out["fonte"] = fonte_padrao
    return out


def main():
    registros: list[dict] = []

    for arquivo, fonte_padrao in FONTES:
        if arquivo.exists():
            with open(arquivo, encoding="utf-8") as f:
                dados = json.load(f)
            norm = [normalizar(d, fonte_padrao) for d in dados]
            registros.extend(norm)
            print(f"{fonte_padrao}: {len(norm)} entradas")
        else:
            print(f"Aviso: {arquivo} nao encontrado")

    # Remove duplicatas: usa url_pdf quando é único por decisão;
    # para fontes onde url_pdf é o PDF container (ex: TRE-MG ementário),
    # combina com numero_processo para ter chave única por decisão.
    vistos: set[str] = set()
    unicos: list[dict] = []
    for r in registros:
        url  = r.get("url_pdf", "")
        num  = r.get("numero_processo", "")
        trib = r.get("tribunal", "")
        if url and num:
            chave = url + "|" + trib + "|" + num
        elif url:
            chave = url
        else:
            chave = trib + "|" + num + "|" + r.get("topico", "") + "|" + r.get("titulo", "")[:80]
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(r)

    with open(MERGED_JSON, "w", encoding="utf-8") as f:
        json.dump(unicos, f, ensure_ascii=False, indent=2)

    print(f"\nMerged: {len(unicos)} decisoes unicas -> {MERGED_JSON}")


if __name__ == "__main__":
    main()
