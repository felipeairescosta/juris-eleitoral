"""
Enriquece jurisprudencia_tse.json baixando PDFs do TSE e extraindo
a ementa completa (substitui resumo truncado em 1500 chars).

Uso: py enriquecer_tse_pdf.py
Progresso salvo a cada 200 registros. Pode ser interrompido e retomado.
"""

import json, re, io, time, warnings, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pdfplumber

warnings.filterwarnings("ignore")

INPUT   = Path("output/jurisprudencia_tse.json")
OUTPUT  = Path("output/jurisprudencia_tse.json")
WORKERS = 12
TIMEOUT = 20
SALVAR_A_CADA = 200

HEADERS = {
    "Referer": "https://temasselecionados.tse.jus.br/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

RE_EMENTA_INICIO = re.compile(
    r"ementado\s*\(ID[^)]+\)\s*:\s*\n(.*)",
    re.DOTALL | re.IGNORECASE,
)
RE_EMENTA_FIM = re.compile(
    r"\n(?:Na origem[,\s]|Vistos[,\s]|Trata-se|O present|A present|"
    r"Assinado eletronicamente|https?://|TRIBUNAL SUPERIOR ELEIT)",
    re.IGNORECASE,
)


def extrair_ementa_pdf(conteudo: bytes) -> str:
    try:
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return ""

    m = RE_EMENTA_INICIO.search(texto)
    if not m:
        return ""

    corpo = m.group(1)
    fim = RE_EMENTA_FIM.search(corpo)
    if fim:
        corpo = corpo[: fim.start()]

    # Limpa linhas de rodapé que pdfplumber joga no meio
    linhas = []
    for l in corpo.splitlines():
        l = l.strip()
        if not l:
            continue
        if re.match(r"https?://|Assinado eletronicamente", l, re.I):
            break
        linhas.append(l)

    return "\n".join(linhas).strip()


def baixar_e_extrair(idx: int, entrada: dict) -> tuple[int, str]:
    url = entrada.get("url_pdf", "")
    if not url or not url.startswith("http"):
        return idx, ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False)
        if r.status_code != 200:
            return idx, ""
        return idx, extrair_ementa_pdf(r.content)
    except Exception:
        return idx, ""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    decisoes = json.loads(INPUT.read_text(encoding="utf-8"))

    # Apenas entradas com resumo truncado (≤ 1500 chars e com url_pdf)
    pendentes = [
        (i, d) for i, d in enumerate(decisoes)
        if len(d.get("resumo", "")) <= 1500 and d.get("url_pdf", "").startswith("http")
    ]
    print(f"Total a enriquecer: {len(pendentes)} de {len(decisoes)}")

    atualizados = 0
    lote_count  = 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futuros = {ex.submit(baixar_e_extrair, i, d): (i, d) for i, d in pendentes}
        for fut in as_completed(futuros):
            idx, ementa = fut.result()
            if ementa and len(ementa) > len(decisoes[idx].get("resumo", "")):
                decisoes[idx]["resumo"] = ementa
                atualizados += 1
            lote_count += 1
            if lote_count % 50 == 0:
                pct = lote_count * 100 // len(pendentes)
                print(f"  {lote_count}/{len(pendentes)} ({pct}%) — enriquecidos: {atualizados}")
            if lote_count % SALVAR_A_CADA == 0:
                OUTPUT.write_text(json.dumps(decisoes, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  [salvo] {atualizados} registros atualizados até agora")

    OUTPUT.write_text(json.dumps(decisoes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nConcluído. {atualizados} de {len(pendentes)} ementas enriquecidas -> {OUTPUT}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"Tempo total: {(time.time()-t0)/60:.1f} min")
