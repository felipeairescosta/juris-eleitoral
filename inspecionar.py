import json
import pprint

with open("output/jurisprudencia.json", encoding="utf-8") as f:
    dados = json.load(f)

print(f"Total de decisoes: {len(dados)}")

topicos = {}
for d in dados:
    t = d["topico"]
    s = d["subtopico"]
    topicos.setdefault(t, {}).setdefault(s, 0)
    topicos[t][s] += 1

for topico, subtopicos in topicos.items():
    total = sum(subtopicos.values())
    print(f"\n[{topico}] — {total} decisoes, {len(subtopicos)} subtopicos:")
    for sub, qtd in list(subtopicos.items())[:8]:
        print(f"  ({qtd}) {sub}")
    if len(subtopicos) > 8:
        print(f"  ... e mais {len(subtopicos) - 8} subtopicos")

print("\n--- Exemplo de decisao ---")
for d in dados[:1]:
    pprint.pprint(d)
