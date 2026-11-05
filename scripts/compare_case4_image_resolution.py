"""Fixed-context original/400-DPI image comparison; independent answer + review."""
import base64
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from literature_rag.config import Settings
from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
from literature_rag.application.agent_loop import REVIEW_PROMPT

OUT = ROOT / '.rag-data/evaluations/case4-resolution-20261106'
LIB = ROOT / '.rag-data/evaluations/agent-eightpapers-20261105/library'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    import fitz
    OUT.mkdir(parents=True, exist_ok=True)
    state = json.loads((ROOT / '.rag-data/agent-runs/agent-figure-discovery-case4-20261106/state.json').read_text('utf-8'))
    template = next(c['input_messages'] for c in state['model_calls'] if c['stage'] == 'finalize')
    ids = ['img_c28013b94774cd7e2957', 'img_d3d031d211114f24044d']
    manifest = json.loads((LIB / 'visual-retrieval.json').read_text('utf-8'))
    assets = [next(a for a in manifest['assets'] if a['id'] == i) for i in ids]
    pdf = next((LIB / 'papers').glob('fc10c27084432887*.pdf'))
    paths = {'original': [], 'high': []}
    with fitz.open(pdf) as doc:
        for i, a in enumerate(assets):
            paths['original'].append(LIB / a['image_path'])
            page = doc[a['page']-1]
            x0,y0,x1,y1 = a['bbox']
            clip = fitz.Rect(x0/1000*page.rect.width,y0/1000*page.rect.height,x1/1000*page.rect.width,y1/1000*page.rect.height)
            dest = OUT / f'high-{i}.png'
            page.get_pixmap(clip=clip,dpi=400,alpha=False).save(dest)
            paths['high'].append(dest)
    settings = Settings(_env_file=ROOT/'backend/.env.literature')
    write(OUT/'manifest.json', dict(model=settings.llm_model, thinking=settings.llm_thinking_enabled,
        reasoning_effort=settings.llm_reasoning_effort, template=template, dpi=400,
        policy='Three independent repetitions per arm, alternating arms; fixed finalize context plus existing review; no regenerated retrieval or gold supplied',
        images={k:[dict(path=str(p),sha256=sha256(p.read_bytes()).hexdigest()) for p in v] for k,v in paths.items()}))
    if '--prepare-only' in sys.argv:return
    adapter = ChatAgentAdapter(settings)
    for repeat in range(1,4):
        for arm in ('original','high'):
            dest=OUT/f'{arm}-{repeat}.json'
            if dest.exists():continue
            marker=dest.with_suffix('.started')
            if marker.exists():raise RuntimeError('Inspect interrupted request before retry')
            marker.write_text('started',encoding='utf-8')
            messages=deepcopy(template); image_index=0
            for m in messages:
                if not isinstance(m.get('content'),list):continue
                for b in m['content']:
                    if b['type']=='image_url':
                        b['image_url']={'url':'data:image/png;base64,'+base64.b64encode(paths[arm][image_index].read_bytes()).decode()}
                        image_index+=1
            assert image_index==2
            result=dict(arm=arm,repeat=repeat,status='started');start=perf_counter()
            try:
                draft=adapter.decide(messages,{},120,8192)
                result.update(draft=draft.text,draft_usage=draft.usage,draft_finish=draft.finish_reason)
                write(dest,result)
                review=adapter.decide(messages+[draft.message,dict(role='user',content=REVIEW_PROMPT)],{},120,8192)
                result.update(answer=review.text,review_usage=review.usage,review_finish=review.finish_reason,status='completed')
            except Exception as e:
                result.update(status='failed',error_type=type(e).__name__)
            result['seconds']=round(perf_counter()-start,2)
            write(dest,result)
            print(arm,repeat,result['status'],flush=True)


if __name__=='__main__':main()
