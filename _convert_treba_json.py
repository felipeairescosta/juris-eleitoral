import json, sys
sys.stdout.reconfigure(encoding='utf-8')

src = json.load(open(r'C:\Users\leona\Downloads\tre_ba_coletaneas_consolidado_completo.json', encoding='utf-8'))

FONTE_MAP = {
    'Registro de Candidatura':              'TRE-BA - Coletânea Registro de Candidatura',
    'Prestação de Contas de Campanha Eleitoral': 'TRE-BA - Coletânea Prestação de Contas',
}
URL_FONTE = 'https://www.tre-ba.jus.br/jurisprudencia/colecoes-tematicas-de-jurisprudencia'

out = []
for doc in src['documentos']:
    tema_geral = doc['fonte']['tema_geral']
    fonte = FONTE_MAP.get(tema_geral, 'TRE-BA - Coletânea Temática')
    for secao in doc['secoes']:
        topico = secao['tema']
        for d in secao['decisoes']:
            meta = d.get('metadados_referencia', {})
            ementa = d.get('ementa', '').strip()
            titulo = ementa.split('\n')[0][:300]
            out.append({
                'topico': topico,
                'subtopico': '',
                'titulo': titulo,
                'numero_processo': meta.get('classe_ou_identificacao', ''),
                'data': meta.get('data_julgamento', ''),
                'relator': meta.get('relator', ''),
                'tribunal': 'TRE-BA',
                'resumo': ementa[:3000],
                'url_pdf': d.get('id', ''),
                'url_fonte': URL_FONTE,
                'fonte': fonte,
            })

print(f'{len(out)} decisoes')
for f in sorted(set(x["fonte"] for x in out)):
    print(f'  {f}: {sum(1 for x in out if x["fonte"]==f)}')

out_path = 'output/jurisprudencia_treba_coletaneas.json'
json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'Salvo em {out_path}')
