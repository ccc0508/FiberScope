from app.agent_answer import adapt_run
from app import literature, agent_answer


def test_default_website_routes_to_agent(monkeypatch):
    config=literature.LiteratureSettings(_env_file=None)
    assert config.engine=='agent' and config.timeout_seconds==300
    monkeypatch.setattr(agent_answer,'run_agent_answer',lambda c,q:dict(answer=q,engine=c.engine))
    assert literature.run_answer(config,'测试')['engine']=='agent'


def test_agent_citation_identity_and_calculation():
    state=dict(status='completed',answer='原文[7]，计算[12]，图片[15]',review_status='completed')
    text=dict(document_id='doc',filename='paper.pdf',page_start=2,page_end=3,text='original',sources=[dict(chunk_id='c',text='original',page_start=2,page_end=3)])
    calc=dict(initial='40',final='50',unit='Nm/g',difference='10',relative_change_percent='25',formula='(final-initial)/initial*100')
    asset=dict(document_id='doc',label='Fig.1',page=3,parent_chunk_id='c')
    evidence=[dict(ref='[7]',kind='source_text',content=text),dict(ref='[12]',kind='calculation',content=calc),dict(ref='[15]',kind='source_image',content=dict(asset=asset)),dict(ref='[16]',kind='source_text',content=text)]
    r=adapt_run(state,evidence,[],12)
    assert [c['ref'] for c in r['citations']]==['[7]','[12]','[15]']
    assert r['citations'][1]['document_id']=='' and r['citations'][1]['kind']=='calculation'
    assert r['citations'][2]['visual_assets']==[asset]
    assert len(r['retrieved_evidence'])==4 and r['agent_evidence']==evidence
    assert r['review_summary']['status']=='completed'


def test_incomplete_run_not_reported_success():
    r=adapt_run(dict(status='partial',answer='draft',review_status='failed'),[],[],1)
    assert r['status']=='failed' and r['review_summary']['status']=='incomplete'
