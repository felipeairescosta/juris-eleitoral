"""
Scraper TRE-RS — EmTema (Ementário Temático Anotado)
Requer: pip install playwright && playwright install chromium

Uso: python scraper_trers.py
Saída: output/jurisprudencia_trers.json

Estrutura do site:
  Tópico (capa) → links de subtópicos → cada subtópico tem ementas + links _inteiroteor
  O número completo do processo está embutido na URL do inteiro teor.
"""

import asyncio
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

OUTPUT = Path("output/jurisprudencia_trers.json")
BASE   = "https://www.tre-rs.jus.br"

# Páginas "capa" de cada tópico principal
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

RE_DATA    = re.compile(r"\b(\d{1,2}[/\.\-]\d{1,2}[/\.\-]\d{2,4})\b")
RE_RELATOR = re.compile(
    r"[Rr]elator[a]?\(?[a-z]?\)?\s*(?:Des\.?a?|Min\.?|Juiz[a]?\.?|Dr\.?a?)?\s*([A-ZÁÉÍÓÚÂÊÎÔÛÃÕÀÇ][A-Za-záéíóúâêîôûãõàçÁÉÍÓÚÂÊÎÔÛÃÕÀÇ\s\.]{5,60}?)(?:\s*[,\n]|$)",
)
# Extrai número CNJ da URL: tre-rs-NNNNNNN-DD-AAAA-J-TT-OOOO_inteiroteor
RE_NUM_URL = re.compile(r"tre-rs-(\d+)-(\d+)-(\d{4})-(\d)-(\d+)-(\d+)_inteiroteor", re.IGNORECASE)


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


async def carregar(page, url: str):
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    await page.wait_for_timeout(1500)


async def coletar_subtopicos(page, topico: str, capa_url: str) -> list[dict]:
    """Coleta todos os links de subtópicos a partir da capa do tópico."""
    await carregar(page, capa_url)
    links = await page.eval_on_selector_all(
        "a[href]",
        "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))"
        f".filter(l => l.href.includes('{BASE}') && l.href.includes('emtema-novo')"
        " && !l.href.includes('#') && l.text.length > 2"
        " && (l.text.match(/^\\d/) || l.text.match(/^[A-Z]/)))"
    )
    # Filtra apenas os que são subtópicos desta capa (mesmo path base)
    base_path = capa_url.rsplit("/", 1)[0]
    subs = [l for l in links if l["href"].startswith(base_path) and l["href"] != capa_url]
    return subs


async def raspar_subtopico(page, topico: str, subtopico: str, url: str) -> list[dict]:
    """Extrai todas as decisões de uma página de subtópico."""
    await carregar(page, url)

    # Coleta pares (link_inteiroteor, texto_da_ementa)
    # Cada decisão tem um link _inteiroteor seguido do texto
    items = await page.evaluate("""() => {
        const resultado = [];
        const links = Array.from(document.querySelectorAll('a[href*="_inteiroteor"]'));
        for (const link of links) {
            const href = link.href;
            const titulo = link.innerText.trim();
            // Pega o texto do bloco pai ou dos irmãos seguintes até o próximo link
            let texto = '';
            let node = link.parentElement;
            // Sobe até encontrar um bloco de conteúdo
            while (node && node.tagName !== 'ARTICLE' && node.tagName !== 'SECTION'
                   && node.tagName !== 'DIV' && node.tagName !== 'MAIN') {
                node = node.parentElement;
            }
            if (node) texto = node.innerText.trim();
            resultado.push({href, titulo, texto: texto.slice(0, 3000)});
        }
        return resultado;
    }""")

    decisoes = []
    for item in items:
        num = num_de_url(item["href"])
        texto = item["texto"] or item["titulo"]
        decisoes.append({
            "topico":           topico,
            "subtopico":        subtopico,
            "titulo":           item["titulo"][:300],
            "numero_processo":  num,
            "data":             extrair_data(texto),
            "relator":          extrair_relator(texto),
            "publicacao":       "",
            "tribunal":         "TRE-RS",
            "resumo":           texto,
            "url_pdf":          item["href"],
            "url_fonte":        url,
            "fonte":            "TRE-RS - Ementário Temático",
        })
    return decisoes


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
                    print(f"    → {nome_sub[:60]}")
                    try:
                        decisoes = await raspar_subtopico(page, topico, nome_sub, sub_url)
                        print(f"       {len(decisoes)} decisão(ões)")
                        todas.extend(decisoes)
                    except Exception as e:
                        print(f"       ERRO: {e}")
                    await asyncio.sleep(0.8)
            except Exception as e:
                print(f"  ERRO na capa: {e}")

        await browser.close()

    OUTPUT.write_text(
        json.dumps(todas, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{'='*50}")
    print(f"Total: {len(todas)} decisões → {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
