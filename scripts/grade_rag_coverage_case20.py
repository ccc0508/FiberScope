"""Jev grade the frozen new case20 only, preserving raw requests/replies."""
import grade_agent_eightpapers_20261105 as g
import os
g.RUN=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-coverage-priority-20261109'
revision=os.environ.get('RAG_CASE20_REVISION','1')
if revision!='1':g.RUN=g.RUN.with_name(g.RUN.name+'-r'+str(int(revision)))
g.LIBRARY=g.ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'
g.OUT=g.RUN/'jev'
g.PACK=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/latest-scored/pack'
g.delivered_refs=lambda result:{r['ref'] for r in result.get('citation_validation',{}).get('available_records',[]) if r.get('citable')}
read_jsonl=g.j.read_jsonl
g.j.read_jsonl=lambda path:[c for c in read_jsonl(path) if c['id']=='FS8-020']
if __name__=='__main__':g.run()
