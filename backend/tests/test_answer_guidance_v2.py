"""The shorter-guidance controller cannot replay changed orchestration or reuse v1 analysis notes."""
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import answer_guidance_v2_20261031 as study


def sealed(tmp_path,monkeypatch):
    (tmp_path/'scripts').mkdir();controller=tmp_path/'scripts/controller.py';controller.write_bytes(b'controller')
    engine=tmp_path/'scripts/engine.py';engine.write_bytes(b'original')
    out=tmp_path/'private';out.mkdir()
    monkeypatch.setattr(study,'ROOT',tmp_path);monkeypatch.setattr(study,'OUTPUT',out)
    monkeypatch.setattr(study,'__file__',str(controller))
    monkeypatch.setattr(study.replay,'check_contract',lambda:None)
    monkeypatch.setattr(study.replay,'OUTPUT',out)
    c=dict(controller_sha256=study.judge.digest(controller),guidance_version=study.VERSION,
        engine_sha256={'engine.py':study.judge.digest(engine)})
    study.judge.write(out/'experiment.json',c)
    return controller,engine,c


@pytest.mark.parametrize('change',['controller','engine','version'])
def test_changed_controller_engine_or_version_halts_before_a_paid_operation(tmp_path,monkeypatch,change):
    controller,engine,c=sealed(tmp_path,monkeypatch);assert study.check_contract()==c
    if change=='controller':controller.write_bytes(b'changed')
    elif change=='engine':engine.write_bytes(b'changed')
    else:
        c['guidance_version']='answer-completeness-v1';study.judge.write(study.OUTPUT/'experiment.json',c)
    with pytest.raises(ValueError):study.execute('run')


def test_new_collection_does_not_inject_prior_study_conclusions(tmp_path,monkeypatch):
    _,_,c=sealed(tmp_path,monkeypatch);received=[]
    def collect(root,out,analyst_notes):
        received.append(analyst_notes)
        return dict(records=[],controls={},provenance={},analyst_notes=analyst_notes)
    monkeypatch.setattr(study.collector,'collect',collect)
    assert study.collect()==dict(records=0,provider_calls=0)
    assert received==[[]]
    payload=study.judge.read_json(study.OUTPUT/'analysis-input.json')
    assert payload['controls']['guidance_version']==study.VERSION and payload['analyst_notes']==[]
    assert payload['provenance']['controller_sha256']==c['controller_sha256']
    notes=tmp_path/'notes.json';study.judge.write(notes,{'fake_score':1})
    with pytest.raises(ValueError):study.collect(notes)


def test_prepared_study_cannot_be_overwritten(tmp_path,monkeypatch):
    sealed(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='never overwrite'):study.prepare()
