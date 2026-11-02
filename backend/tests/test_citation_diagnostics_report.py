"""Diagnostic exports preserve failures and mark old records unavailable without model calls."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_qa_citation_failures as report
from literature_rag.application.citations import RecordingCitationValidator
from literature_rag.domain.errors import CitationValidationError
from literature_rag.domain.models import GeneratedAnswer,GeneratedClaim
from tests.test_literature_answers import make_evidence


def body():
    validator=RecordingCitationValidator()
    with pytest.raises(CitationValidationError):
        validator.validate(GeneratedAnswer('<script>untrusted draft</script>',
            (GeneratedClaim('Synthetic claim',('[1]',)),)),[make_evidence()])
    return dict(status='refused',answer='Synthetic guarded refusal',reason_code='citation_validation_failed',
                citation_validation=validator.snapshot())


@pytest.mark.parametrize('shape',['worker','evaluation','history'])
def test_worker_run_results_and_history_exports_keep_the_same_trace(tmp_path,shape):
    result=body()
    value=result if shape=='worker' else dict(question='Synthetic question',**({'task_id':'TEST','response':result} if shape=='evaluation' else {'id':'TEST','result':result}))
    source=tmp_path/('source.jsonl' if shape=='history' else 'source.json')
    source.write_text(json.dumps(value,ensure_ascii=False)+'\n',encoding='utf-8')
    original=source.read_bytes()
    output=tmp_path/'report'
    summary=report.publish(source,output)
    assert summary['failed_validation_attempts']==1 and summary['model_calls']==0
    assert not summary['answers_or_scores_changed'] and source.read_bytes()==original
    row=json.loads((output/'records.jsonl').read_text(encoding='utf-8'))
    assert row['citation_validation']==result['citation_validation']
    assert row['source']['sha256']==sha256(original).hexdigest()
    html=(output/'report.html').read_text(encoding='utf-8')
    assert '<script>untrusted draft</script>' not in html and '&lt;script&gt;untrusted draft&lt;/script&gt;' in html
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    assert all(sha256((output/name).read_bytes()).hexdigest()==checksum for name,checksum in manifest['files'].items())
    with pytest.raises(ValueError,match='overwrite'):report.publish(source,output)


def test_old_refusal_is_unavailable_not_reconstructed_or_given_zero(tmp_path):
    run=tmp_path/'run';(run/'results').mkdir(parents=True)
    (run/'results/OLD.json').write_text(json.dumps(dict(task_id='OLD',response=dict(status='refused',answer='Old refusal'))),encoding='utf-8')
    summary=report.publish(run,tmp_path/'out')
    assert summary['unavailable_records']==1 and summary['failed_validation_attempts']==0
    row=json.loads((tmp_path/'out/records.jsonl').read_text(encoding='utf-8'))
    assert row['citation_validation'] is None and 'score' not in row


def test_tampered_draft_is_rejected_before_writing_any_report(tmp_path):
    value=body();value['citation_validation']['attempts'][0]['draft']['answer']='Tampered'
    path=tmp_path/'changed.json';path.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='checksum'):report.publish(path,tmp_path/'report')
    assert not (tmp_path/'report').exists()


def test_offline_cli_reports_old_missing_diagnostics_without_touching_results(tmp_path):
    source=tmp_path/'old.json';source.write_text(json.dumps(dict(status='refused',answer='Synthetic old refusal')),encoding='utf-8')
    p=subprocess.run([sys.executable,str(ROOT/'scripts/report_qa_citation_failures.py'),'--input',str(source),
        '--output',str(tmp_path/'out')],capture_output=True,text=True,encoding='utf-8')
    assert p.returncode==0
    assert json.loads(p.stdout)['unavailable_records']==1
