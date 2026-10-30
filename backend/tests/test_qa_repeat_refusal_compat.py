"""Production refusals stay sealed and unchanged; malformed results still fail."""
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import qa_repeat_refusal_compat as compat


def fixture(tmp_path):
    (tmp_path/'results').mkdir();(tmp_path/'attempts').mkdir()
    result=dict(run_id='run',task_id='A',case_id='A',question='Q',status='refused',response=dict(
        status='refused',answer='No reliable answer.',claims=[],citations=[]))
    path=tmp_path/'results/A.json';path.write_text(json.dumps(result),encoding='utf-8')
    (tmp_path/'attempts/A.json').write_text(json.dumps(dict(result_sha256=compat.judge.digest(path))),encoding='utf-8')
    return path,result


def test_valid_refusal_is_returned_without_normalizing_or_rewriting_status(tmp_path):
    path,result=fixture(tmp_path);before=path.read_bytes()
    found,actual=compat.read_result(tmp_path,{'run_id':'run'},{'id':'A','question':'Q'},{'id':'A'})
    assert actual==result and actual['status']=='refused' and found==path and path.read_bytes()==before


@pytest.mark.parametrize('defect',['wrong_question','bad_seal','claims'])
def test_refusal_checks_identity_seal_and_empty_scientific_claims(tmp_path,defect):
    path,result=fixture(tmp_path)
    if defect=='wrong_question':result['question']='different'
    elif defect=='claims':result['response']['claims']=[{'text':'invented'}]
    path.write_text(json.dumps(result)+' ',encoding='utf-8')
    if defect!='bad_seal':
        (tmp_path/'attempts/A.json').write_text(json.dumps(dict(result_sha256=compat.judge.digest(path))),encoding='utf-8')
    with pytest.raises(ValueError):compat.read_result(tmp_path,{'run_id':'run'},{'id':'A','question':'Q'},{'id':'A'})


def test_compatibility_scope_restores_original_reader_after_exception():
    before=compat.judge.read_result
    with pytest.raises(RuntimeError):
        with compat.compatible_results():
            assert compat.judge.read_result is compat.read_result
            raise RuntimeError('stop')
    assert compat.judge.read_result is before
