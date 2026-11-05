"""Validate pack structure and optionally the exact local corpus; no paid calls."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path)
    args = parser.parse_args()
    read = lambda name: json.loads((ROOT/name).read_text(encoding='utf-8'))
    lines = lambda name: [json.loads(x) for x in (ROOT/name).read_text(encoding='utf-8').splitlines()]
    sources = {x['id']: x for x in read('sources.json')}
    cases, questions = lines('gold.jsonl'), lines('questions.jsonl')
    assert len(sources) == 8
    assert len(cases) == len(questions) == 30
    assert [x['id'] for x in cases] == [f'FS8-{i:03}' for i in range(1,31)]
    assert Counter(x['group'] for x in cases) == {'single':16, 'cross':8, 'no_paper':6}
    single = Counter()
    prompt=(ROOT/'answer-instructions.md').read_text(encoding='utf-8')
    for c,q in zip(cases, questions):
        assert q == {'id':c['id'], 'question':c['question']}
        assert (ROOT/'tasks'/f"{c['id']}.md").read_text(encoding='utf-8') == prompt+'\n\n## 本题\n\n'+c['question']+'\n'
        assert c['key_points'] and all(c['key_points']) and c['reference_answer'] and c['critical_errors']
        docs={r['document'] for r in c['evidence']}
        if c['group']=='single':
            assert len(docs)==1
            single.update(docs)
        elif c['group']=='cross':
            assert len(docs)>=2
        else:
            assert not docs and not c['citation_applicable']
        assert c['citation_applicable'] == bool(docs)
        for r in c['evidence']:
            assert r['document'] in sources and r['locator'] and r['pages']
            assert all(1<=p<=sources[r['document']]['pdf_pages'] for p in r['pages'])
    assert single==Counter({d:2 for d in sources})
    assert len(list((ROOT/'tasks').glob('*.md')))==30
    read('rubric.json')
    if args.library:
        import fitz
        for s in sources.values():
            path=args.library/s['library_relative_path']
            assert hashlib.sha256(path.read_bytes()).hexdigest()==s['sha256'], s['id']
            with fitz.open(path) as pdf:
                assert len(pdf)==s['pdf_pages'], s['id']
    print(json.dumps({'cases':30,'single':16,'cross':8,'no_paper':6,'documents':8,'two_single_per_document':True,'answer_leak_check':'passed','source_hashes':'verified' if args.library else 'not_checked','scientific_review':'not_replaced_by_this_check'},ensure_ascii=False))

if __name__=='__main__':
    main()
