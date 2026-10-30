"""Original Jev policy and first-valid bounds are sealed before paid A/B grading."""
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import grade_answer_guidance_20261031 as grade


def test_two_arms_have_separate_score_storage():
    paths=grade.entries()
    assert {p['arm'] for p in paths}=={'control','guidance'}
    assert len({p['study_dir'] for p in paths})==2 and all(p['study_dir'].name==p['arm'] for p in paths)


def test_judge_contract_keeps_original_policy_and_rejects_provider_changes(tmp_path,monkeypatch):
    scripts=tmp_path/'scripts';scripts.mkdir();hashes={}
    for name in set(grade.grading.HARNESS)|{'grade_qa_rerank_repeats_20261031.py','qa_repeat_refusal_compat.py'}:
        p=scripts/name;p.write_bytes(b'frozen');hashes[name]=grade.judge.digest(p)
    prior=tmp_path/'.rag-data/evaluations/content-units-jev-20261030-r1';prior.mkdir(parents=True)
    (prior/'study.json').write_text(json.dumps(dict(requested_judges={'jev':{'model':'same'}},policy_sha256=grade.grading.POLICY_SHA,
        harness_files={n:hashes[n] for n in grade.grading.HARNESS})),encoding='utf-8')
    out=tmp_path/'experiment';out.mkdir();monkeypatch.setattr(grade,'ROOT',tmp_path);monkeypatch.setattr(grade,'OUTPUT',out)
    monkeypatch.setattr(grade.grading,'public_settings',lambda s:s)
    c=grade.contract({'jev':{'model':'same'}})
    assert c['first_valid_only'] and c['max_attempts']==3 and c['new_luna_calls']==0 and not c['previous_scores_supplied']
    with pytest.raises(ValueError):grade.contract({'jev':{'model':'changed'}})
    assert grade.contract({'jev':{'model':'same'}})==c
