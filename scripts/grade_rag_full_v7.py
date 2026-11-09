"""Grade completed RAG answers; failed executions stay visible, not sent as empty answers."""
import grade_agent_eightpapers_20261105 as g

g.RUN=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/rag-full-v7-20261109'
g.LIBRARY=g.ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'
g.OUT=g.RUN/'jev'
g.PACK=g.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/latest-scored/pack'
g.delivered_refs=lambda result: {r['ref'] for r in result.get('citation_validation',{}).get('available_records',[]) if r.get('citable')}
read_jsonl=g.j.read_jsonl
def completed_cases(path):
    return [c for c in read_jsonl(path) if (g.RUN/(c['id']+'.json')).exists()
            and g.j.read_json(g.RUN/(c['id']+'.json')).get('status')=='completed']
g.j.read_jsonl=completed_cases
if __name__=='__main__':g.run()
