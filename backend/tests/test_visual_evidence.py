"""Actual image payloads, immutable provenance, fusion and bounded visual selection."""
import base64
from dataclasses import asdict,replace
from hashlib import sha256
import json
from types import SimpleNamespace as NS

import pytest

from literature_rag.application.visual_evidence import VisualCatalog,VisualVectorSearch,verified_image_path,visual_content,VERSION
from literature_rag.application.citations import CitationValidator
from literature_rag.adapters.providers.deepseek import DeepSeekGenerator
from literature_rag.domain.models import VisualAsset,Chunk,Evidence,EvidenceSource,VectorMatch
from literature_rag.domain.errors import InfrastructureError
from tests.literature_fakes import InMemoryMetadataStore

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jYz0AAAAASUVORK5CYII=')


def fixture(tmp_path):
    (tmp_path/'visual-assets').mkdir()
    checksum=sha256(PNG).hexdigest();path=f'visual-assets/{checksum}.png';(tmp_path/path).write_bytes(PNG)
    chunks=[Chunk(f'c{i}','doc','paper.pdf',i,i,i,f'Figure {i}. Caption',5,'fake',kind='figure_caption') for i in [1,2,9]]
    assets=[VisualAsset(f'img{i}','doc',c.id,f'Figure {i}',i,(10,10,100,100),path,checksum,1,1,len(PNG)) for i,c in zip([1,2,9],chunks)]
    manifest=dict(version=VERSION,status='ready',embedding=dict(provider='test',model='fake',dimensions=3),
        assets=[asdict(a) for a in assets],parent_text_sha256={c.id:sha256(c.text.encode()).hexdigest() for c in chunks})
    metadata=InMemoryMetadataStore();metadata.chunks={c.id:c for c in chunks}
    cat=VisualCatalog(tmp_path,manifest,{a.id:[1.,0.,0.] for a in assets},metadata)
    evidences=[Evidence(f'[{i+1}]',c.id,c.document_id,c.filename,c.page_start,c.page_end,c.text,.8,
        source_chunks=(EvidenceSource(c.id,c.chunk_index,c.page_start,c.page_end,c.text,c.kind),)) for i,c in enumerate(chunks)]
    return cat,evidences,assets


def test_image_vector_maps_to_original_parent_and_deduplicates_text_hit(tmp_path):
    cat,_,_=fixture(tmp_path)
    search=VisualVectorSearch(NS(search=lambda *_:[VectorMatch('c1',.5)],last_diagnostics={'row_candidates':2}),cat)
    result=search.search([1.,0.,0.],50)
    assert len(result)==3 and len({m.chunk_id for m in result})==3
    assert next(m for m in result if m.chunk_id=='c1').score==1
    assert search.last_diagnostics['row_candidates']==2 and len(search.last_visual_diagnostics['image_hits'])==3
    with pytest.raises(InfrastructureError):search.search([0.,0.,0.],50)


def test_requested_image_priority_budget_and_source_membership(tmp_path):
    cat,es,assets=fixture(tmp_path)
    result,info=cat.attach(es,es,'Explain Figure 9',max_images=1)
    assert [a.id for e in result for a in e.visual_assets]==['img9']
    assert info['selected'][0]['ref']=='[3]' and len(info['omitted'])==2
    result,info=cat.attach(es[:1],es[:1],'Explain Figure 9',max_images=4)
    assert [a.id for e in result for a in e.visual_assets]==['img1']
    result,info=cat.attach(es,es,'Figures',max_total_bytes=len(PNG)-1)
    assert info['image_count']==0 and all(not e.visual_assets for e in result)


def test_original_image_hash_path_and_parent_integrity_are_required(tmp_path):
    cat,_,assets=fixture(tmp_path);a=assets[0]
    with pytest.raises(InfrastructureError):verified_image_path(tmp_path,replace(a,image_path='../private.png'))
    with pytest.raises(InfrastructureError):verified_image_path(tmp_path,replace(a,image_path=str((tmp_path/a.image_path).resolve())))
    (tmp_path/a.image_path).write_bytes(PNG+b'changed')
    with pytest.raises(InfrastructureError):verified_image_path(tmp_path,a)


def test_deepseek_sends_original_image_bytes_with_exact_ref_and_keeps_usage_not_base64(tmp_path):
    cat,es,_=fixture(tmp_path);es,info=cat.attach(es[:1],es[:1],'Figure 1')
    requests=[]
    def create(**kwargs):
        requests.append(kwargs)
        return NS(model='deepseek-flash',system_fingerprint='fixture',usage=NS(prompt_tokens=100,completion_tokens=10,total_tokens=110),
            choices=[NS(message=NS(content=json.dumps(dict(answer='A visual observation [1]',
                claims=[dict(text='A visual observation',citation_refs=['[1]'])]))))])
    generator=DeepSeekGenerator('deepseek-flash','PRIVATE',client=NS(chat=NS(completions=NS(create=create))),
        thinking_enabled=True,reasoning_effort='high',visual_root=tmp_path)
    answer=generator.generate('Original question',es)
    body=requests[0];blocks=body['messages'][1]['content']
    assert isinstance(blocks,list) and 'Original question' in blocks[0]['text']
    image=next(b for b in blocks if b['type']=='image_url')['image_url']
    assert base64.b64decode(image['url'].split(',',1)[1])==PNG and image['detail']=='original'
    assert any('[1] ORIGINAL PDF IMAGE: Figure 1' in b.get('text','') for b in blocks)
    assert body['reasoning_effort']=='high' and body['extra_body']=={'thinking':{'type':'enabled'}}
    assert generator.last_model_info['image_count']==1 and 'base64' not in repr(generator.last_model_info)
    citation=CitationValidator().validate(answer,es).citations[0]
    assert citation.visual_assets==es[0].visual_assets


def test_changed_original_image_fails_before_any_model_call(tmp_path):
    cat,es,assets=fixture(tmp_path);es,_=cat.attach(es,es,'Figure 1')
    (tmp_path/assets[0].image_path).write_bytes(PNG+b'changed')
    generator=DeepSeekGenerator('deepseek-flash','PRIVATE',visual_root=tmp_path,
        client=NS(chat=NS(completions=NS(create=lambda **_:pytest.fail('must not send changed image')))))
    with pytest.raises(InfrastructureError):generator.generate('Question',es)
