"""Paired round scheduling and no-regeneration guarantees without provider calls."""
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import repeat_qa_rerank_20261031 as repeat


def test_plan_reuses_original_two_baselines_and_makes_four_independent_runs(tmp_path):
    plan=repeat.preparation_plan(tmp_path)
    assert len(plan)==4 and len({p['run_dir'] for p in plan})==4
    assert {(p['system'],p['round']) for p in plan}=={(s,r) for s in ['content','rerank'] for r in [2,3]}
    for p in plan:
        assert p['original_run_dir']!=p['run_dir']
        assert p['baseline'].endswith('qa-content-units-v1-20261030' if p['system']=='content' else 'qa-candidate-rerank-v1-20261030')


def test_submission_order_alternates_and_reverses_in_next_round():
    two=list(repeat.pair_schedule(['A','B','C'],2));three=list(repeat.pair_schedule(['A','B','C'],3))
    assert two==[('A',['content','rerank']),('B',['rerank','content']),('C',['content','rerank'])]
    assert all(a==b and x==list(reversed(y)) for (a,x),(b,y) in zip(two,three,strict=True))
    with pytest.raises(ValueError):list(repeat.pair_schedule(['A','A'],2))


def test_completed_failed_answer_is_kept_instead_of_regenerated(tmp_path,monkeypatch):
    (tmp_path/'results').mkdir();(tmp_path/'attempts').mkdir()
    result=tmp_path/'results/A.json';result.write_text(json.dumps({'status':'failed'}),encoding='utf-8')
    (tmp_path/'attempts/A.json').write_text(json.dumps({'result_sha256':repeat.judge.digest(result)}),encoding='utf-8')
    def unexpected(*args,**kwargs):raise AssertionError('Completed failure was regenerated')
    monkeypatch.setattr(repeat.runner,'run',unexpected)
    assert repeat.run_one({'run_dir':str(tmp_path)},'A',['A'])=='failed'


def test_pairing_rejects_skipping_an_unattempted_question(tmp_path):
    (tmp_path/'results').mkdir()
    with pytest.raises(ValueError,match='alignment'):
        repeat.run_one({'run_dir':str(tmp_path)},'B',['A','B'])
