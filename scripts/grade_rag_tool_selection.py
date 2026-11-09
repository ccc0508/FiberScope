"""Jev grading of two frozen answers, with original source context."""
import grade_agent_eightpapers_20261105 as g
g.RUN=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-tool-selection-20261109'
g.LIBRARY=g.ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'
g.OUT=g.RUN/'jev'
g.PACK=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/latest-scored/pack'
g.delivered_refs=lambda result:{r['ref'] for r in result.get('citation_validation',{}).get('available_records',[]) if r.get('citable')}
read_jsonl=g.j.read_jsonl
g.j.read_jsonl=lambda path:[c for c in read_jsonl(path) if c['id'] in ['FS8-012','FS8-017']]
if __name__=='__main__':g.run()
