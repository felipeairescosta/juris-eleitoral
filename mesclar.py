"""
Mescla os JSONs do TRE-CE e do TSE num único arquivo consolidado.
Uso: python mesclar.py
"""

import json
from pathlib import Path

TRECE_JSON   = Path("output/jurisprudencia.json")
TSE_JSON     = Path("output/jurisprudencia_tse.json")
SUMULAS_JSON     = Path("output/jurisprudencia_sumulas_trece.json")
SUMULAS_TSE_JSON = Path("output/jurisprudencia_sumulas_tse.json")
MERGED_JSON      = Path("output/jurisprudencia_merged.json")

FONTES = [
    (TRECE_JSON,      "TRE-CE - Ementários Temáticos"),
    (TSE_JSON,        "TSE - Temas Selecionados"),
    (SUMULAS_JSON,    "TRE-CE - Súmulas"),
    (SUMULAS_TSE_JSON, "TSE - Súmulas"),
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

    # Remove duplicatas por url_pdf (mantém o primeiro)
    vistos: set[str] = set()
    unicos: list[dict] = []
    for r in registros:
        chave = r.get("url_pdf") or (r.get("topico", "") + r.get("titulo", ""))
        if chave and chave not in vistos:
            vistos.add(chave)
            unicos.append(r)

    with open(MERGED_JSON, "w", encoding="utf-8") as f:
        json.dump(unicos, f, ensure_ascii=False, indent=2)

    print(f"\nMerged: {len(unicos)} decisoes unicas -> {MERGED_JSON}")


if __name__ == "__main__":
    main()
