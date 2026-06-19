"""
Scraper TRE-RS — EmTema (Ementário Temático Anotado)
Requer: pip install playwright && playwright install chromium

Uso: python scraper_trers.py
Saída: output/jurisprudencia_trers.json

Estrutura do site:
  capa -> links de subtópicos -> cada subtópico contém <p> com link + <p> irmãos com ementa
  Links de documento: /arquivos/tre-rs-NNNNNNN-DD-AAAA-J-TT[-.]OOOO[_inteiroteor]
  Links de subpágina: terminam em -1, -2 etc. (mais decisões antigas)
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT = Path("output/jurisprudencia_trers.json")
BASE   = "https://www.tre-rs.jus.br"

CAPAS = [
    ("Abuso de Poder",
     f"{BASE}/jurisprudencia/emtema-novo/abuso-de-poder/capa-abuso-de-poder"),
    ("Captação Ilícita de Sufrágio",
     f"{BASE}/jurisprudencia/emtema-novo/captacao-ilicita-de-sufragio/captacao-ilicita-de-sufragio-art-41-a-da-lei-n-9504-97-1"),
    ("Condutas Vedadas a Agentes Públicos",
     f"{BASE}/jurisprudencia/emtema-novo/condutas-vedadas-a-agentes-publicos/condutas-vedadas-a-agentes-publicos2"),
    ("Crimes Eleitorais",
     f"{BASE}/jurisprudencia/emtema-novo/crimes-eleitorais/crimes-eleitorais"),
    ("Direito Processual Eleitoral",
     f"{BASE}/jurisprudencia/emtema-novo/direito-processual-eleitoral/copy29_of_teste-de-transporte"),
    ("Direito Processual Penal Eleitoral",
     f"{BASE}/jurisprudencia/emtema-novo/direito-processual-penal-eleitoral/copy4_of_direito-processual-penal-eleitoral"),
    ("Pesquisas e Enquetes Eleitorais",
     f"{BASE}/jurisprudencia/emtema-novo/pesquisas-eleitorais/copy2_of_pesquisas-eleitorais"),
    ("Prestação de Contas Eleitorais – Candidatos",
     f"{BASE}/jurisprudencia/emtema-novo/prestacao-de-contas-eleitorais-candidatos/copy10_of_prestacao-de-contas-eleitorais-candidatos"),
    ("Prestação de Contas Eleitorais – Partidos Políticos",
     f"{BASE}/jurisprudencia/emtema-novo/prestacao-de-contas-eleitorais/copy5_of_debito-eleitoral-acao-anulatoria"),
    ("Prestação de Contas Partidárias",
     f"{BASE}/jurisprudencia/emtema-novo/prestacao-de-contas-partidarias/copy4_of_prestacao-de-contas-partidarias"),
    ("Propaganda Eleitoral",
     f"{BASE}/jurisprudencia/emtema-novo/propaganda-eleitoral/copy5_of_propaganda-eleitoral-1"),
    ("Registro de Candidaturas",
     f"{BASE}/jurisprudencia/emtema-novo/registro-de-candidaturas/copy23_of_registro-de-candidaturas"),
    ("Cassações",
     f"{BASE}/jurisprudencia/emtema-novo/cassacoes/copy_of_cassacoes"),
    ("Infidelidade Partidária",
     f"{BASE}/jurisprudencia/emtema-novo/infidelidade-partidaria/infidelidade-partidaria"),
]

# Extrai CNJ do caminho da URL:
# tre-rs[-re]-NNNNNNN-DD-AAAA-J-TT[-.]OOOO[_inteiroteor]
RE_NUM_URL = re.compile(
    r"tre-rs-(?:re-)?(\d{4,7})-(\d{2})-(\d{4})-(\d)-(\d{2,3})[-\.](\d{4})",
    re.IGNORECASE,
)
RE_DATA      = re.compile(r"\b(\d{1,2}[/\.\-]\d{1,2}[/\.\-]\d{2,4})\b")
RE_RELATOR   = re.compile(
    r"[Rr]elator[a]?\(?[a-z]?\)?\s*(?:[A-Z][a-z]+\.?)?\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇ][A-Za-záéíóúâêîôûãõàçÁÉÍÓÚÂÊÎÔÛÃÕÀÇ\s\.\'`]{5,70}?)(?:\s*[,\n\)]|$)"
)
RE_NUM_TEXTO = re.compile(r"n[º°\.]?\s*0*(\d{5,7}[-\.]?\d{0,2})", re.IGNORECASE)


def num_de_url(url: str) -> str:
    m = RE_NUM_URL.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}.{m.group(3)}.{m.group(4)}.{m.group(5)}.{m.group(6)}"
    return ""


def extrair_data(texto: str) -> str:
    m = RE_DATA.search(texto)
    return m.group(1) if m else ""


def extrair_relator(texto: str) -> str:
    m = RE_RELATOR.search(texto)
    return m.group(1).strip()[:70] if m else ""


def extrair_num_texto(texto: str) -> str:
    m = RE_NUM_TEXTO.search(texto)
    return m.group(1).strip() if m else ""


async def carregar(page, url: str):
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(1200)


async def coletar_subtopicos(page, topico: str, capa_url: str) -> list[dict]:
    await carregar(page, capa_url)
    base_path = capa_url.rsplit("/", 1)[0]
    links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
        ".filter(l => !l.href.includes('#') && l.text.length > 2)"
    )
    vistos = set()
    subs = []
    for l in links:
        href = l["href"]
        txt  = l["text"]
        if (href.startswith(base_path)
                and href != capa_url
                and "arquivos" not in href
                and href not in vistos
                and (txt[0].isdigit() or txt[0].isupper())):
            vistos.add(href)
            subs.append(l)
    return subs


async def extrair_decisoes_da_pagina(page, topico: str, subtopico: str, url: str) -> list[dict]:
    """
    Extrai decisões de uma página de subtópico.
    Cada decisão: <p><a href="/arquivos/...">título</a></p> seguido de <p>ementa</p>...
    """
    items = await page.evaluate("""() => {
        const resultado = [];
        // Todos os links de documento (/arquivos/)
        const links = Array.from(document.querySelectorAll('a[href*="arquivos"]'));
        for (const link of links) {
            const href = link.href;
            const linkText = link.innerText.trim();

            // Sobe ao <p> ou <li> pai direto do link
            let pEl = link.parentElement;
            while (pEl && !['P','LI','DT','DD'].includes(pEl.tagName)) {
                pEl = pEl.parentElement;
            }

            // Coleta parágrafos irmãos seguintes até o próximo link de arquivo
            let resumo = '';
            if (pEl) {
                let sib = pEl.nextElementSibling;
                let count = 0;
                while (sib && count < 15) {
                    // Para se encontrar outro link de arquivo
                    if (sib.querySelector('a[href*="arquivos"]')) break;
                    const t = sib.innerText.trim();
                    if (t) resumo += t + '\\n';
                    sib = sib.nextElementSibling;
                    count++;
                }
            }
            resultado.push({href, linkText, resumo: resumo.trim().slice(0, 3000)});
        }
        return resultado;
    }""")

    decisoes = []
    for item in items:
        titulo  = item["linkText"]
        resumo  = item["resumo"]
        href    = item["href"]
        num_url = num_de_url(href)
        num     = num_url or extrair_num_texto(titulo)
        data    = extrair_data(titulo) or extrair_data(resumo)
        relator = extrair_relator(titulo) or extrair_relator(resumo)

        decisoes.append({
            "topico":           topico,
            "subtopico":        subtopico,
            "titulo":           titulo[:300],
            "numero_processo":  num,
            "data":             data,
            "relator":          relator,
            "publicacao":       "",
            "tribunal":         "TRE-RS",
            "resumo":           (titulo + "\n" + resumo).strip(),
            "url_pdf":          href,
            "url_fonte":        url,
            "fonte":            "TRE-RS - Ementário Temático",
        })
    return decisoes


async def raspar_subtopico(page, topico: str, subtopico: str, url: str) -> list[dict]:
    """Raspa uma página de subtópico, incluindo subpáginas paginadas (-1, -2, etc.)."""
    await carregar(page, url)
    todas = await extrair_decisoes_da_pagina(page, topico, subtopico, url)

    # Verifica subpáginas (-1, -2, ...) na mesma área
    base = url.rsplit("/", 1)[0]
    slug = url.rsplit("/", 1)[-1]
    links_sub = await page.eval_on_selector_all(
        "a[href]",
        f"els => els.map(e => e.href).filter(h => h.startsWith('{base}') && h !== '{url}' && !h.includes('arquivos') && !h.includes('#'))"
    )
    vistos = {url}
    for sub_url in links_sub:
        # Só segue links que parecem subpáginas do mesmo subtópico (slug base igual)
        sub_slug = sub_url.rsplit("/", 1)[-1]
        if sub_slug.startswith(slug.rstrip("0123456789").rstrip("-")) or sub_slug.replace(slug, "").lstrip("-").isdigit():
            if sub_url not in vistos:
                vistos.add(sub_url)
                await carregar(page, sub_url)
                mais = await extrair_decisoes_da_pagina(page, topico, subtopico, sub_url)
                todas.extend(mais)

    return todas


async def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    todas = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="pt-BR",
        )
        page = await context.new_page()

        for topico, capa_url in CAPAS:
            print(f"\n[{topico}]")
            try:
                subs = await coletar_subtopicos(page, topico, capa_url)
                print(f"  {len(subs)} subtópico(s)")
                for sub in subs:
                    nome_sub = sub["text"]
                    sub_url  = sub["href"]
                    print(f"    -> {nome_sub[:55]}", end=" ", flush=True)
                    try:
                        decisoes = await raspar_subtopico(page, topico, nome_sub, sub_url)
                        print(f"({len(decisoes)})")
                        todas.extend(decisoes)
                    except Exception as e:
                        print(f"ERRO: {e}")
                    await asyncio.sleep(0.6)
            except Exception as e:
                print(f"  ERRO na capa: {e}")

        await browser.close()

    OUTPUT.write_text(
        json.dumps(todas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{'='*50}")
    print(f"Total: {len(todas)} decisões -> {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
