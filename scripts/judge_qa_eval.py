"""Grade saved v2 answers with an independent API model; never modify answers or historic reviews."""
from __future__ import annotations

import argparse
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import difflib
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

import qa_judge_prompt as prompt
from qa_eval_v2 import inventory, validate_pack
from score_qa_eval_v2 import review_task, summarize
from validate_qa_eval import child, digest, normalized, read_json, read_jsonl, require


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ('judge_qa_eval.py', 'qa_judge_prompt.py', 'score_qa_eval_v2.py',
           'qa_eval_v2.py', 'validate_qa_eval.py')
SAFE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def sha(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


@dataclass(frozen=True)
class Config:
    base_url: str
    model: str
    api_key: str = field(repr=False)
    api: str = 'responses'
    timeout: float = 180
    max_output_tokens: int = 16000

    def public(self):
        return dict(base_url=self.base_url, requested_model=self.model, api=self.api,
                    timeout_seconds=self.timeout, max_output_tokens=self.max_output_tokens,
                    automatic_retries=0, sampling='Provider defaults; no temperature/top_p/seed override.')


def load_config(path):
    require(path.is_file(), 'Judge configuration file is missing')
    values = dotenv_values(path, interpolate=False)
    def get(name, default=''):
        key = 'QA_JUDGE_' + name
        return (os.environ.get(key, values.get(key, default)) or '').strip()
    base, model, key = get('BASE_URL').rstrip('/'), get('MODEL'), get('API_KEY')
    parsed = urlsplit(base)
    require(parsed.scheme == 'https' and bool(parsed.netloc) and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment, 'Judge base URL must be HTTPS without credentials/query')
    require(bool(model) and bool(key), 'Judge model or private API key is missing')
    mode = get('API', 'responses')
    require(mode in {'responses', 'chat_completions'}, 'Unknown judge API mode')
    timeout, tokens = float(get('TIMEOUT_SECONDS', '180')), int(get('MAX_OUTPUT_TOKENS', '16000'))
    require(1 <= timeout <= 600 and 256 <= tokens <= 64000, 'Invalid judge timeout/output limit')
    return Config(base, model, key, mode, timeout, tokens)


def source_context(pack, manifest):
    evidence = read_json(pack / 'evidence.json')
    texts = {name: (pack / name).read_text(encoding='utf-8')
             for name in manifest['files'] if name.startswith('source/') and name.endswith('.txt')}
    # This dataset is single-document. Do not associate arbitrary future texts with the wrong PDF.
    require(len(manifest['source_documents']) == 1 and len(texts) == 1,
            'Judge v1 requires exactly one explicitly mapped fulltext and document')
    document = manifest['source_documents'][0]
    name, text = next(iter(texts.items()))
    return {'reference_evidence': evidence,
            'paper_texts': [{'document_id': document['id'], 'path': name,
                             'sha256': manifest['files'][name], 'text': text}]}


def verify_run(run_dir):
    run = read_json(run_dir / 'run.json')
    pack = run_dir / 'dataset'
    validate_pack(pack)
    require(digest(pack / 'manifest.json') == run['dataset_manifest_sha256'], 'Run dataset fingerprint mismatch')
    require({**inventory(pack), 'manifest.json': digest(pack / 'manifest.json')} == run['dataset_files'],
            'Run dataset files changed')
    manifest = read_json(pack / 'manifest.json')
    canonical = {t['id']: t for t in read_json(pack / 'tasks.json')}
    require(len({t['id'] for t in run['tasks']}) == len(run['tasks']), 'Duplicate source task')
    for task in run['tasks']:
        require(SAFE_ID.fullmatch(task['id']) and canonical.get(task['id']) == task, 'Invalid source task contract')
    cases = {c['id']: c for c in read_jsonl(pack / 'cases.jsonl')}
    return run, manifest, cases, source_context(pack, manifest)


def read_result(run_dir, run, case, task):
    path = child(run_dir / 'results', task['id'] + '.json')
    result = read_json(path)
    require(result['run_id'] == run['run_id'] and result['task_id'] == task['id']
            and result['case_id'] == case['id'] and result['question'] == case['question'], 'Source result identity mismatch')
    attempt = read_json(run_dir / 'attempts' / (task['id'] + '.json'))
    require(attempt.get('result_sha256') == digest(path), 'Source answer checksum mismatch')
    require(result['status'] in {'answered', 'abstained', 'failed'}, 'Unknown source response status')
    return path, result


def packet(case, task, result, manifest, sources, rubric, validation_feedback=None):
    response = result.get('response') or {}
    # Allowlist only scientific content. Never pass old reviews, answer-model identity, costs or timestamps.
    candidate = {key: response.get(key, [] if key != 'answer' else '')
                 for key in ('answer', 'claims', 'citations', 'retrieved_evidence')}
    task_contract = {k: task[k] for k in ('suite', 'mode', 'capabilities', 'variant') if k in task}
    task_contract['retrieval_applicability'] = prompt.retrieval_applicability(case, task)
    case_contract = {k: case[k] for k in ('id', 'category', 'question', 'expected_behavior',
                                         'reference_answer', 'key_points', 'critical_errors')}
    rules = {k: v for k, v in rubric.items() if k not in {'judge_policy', 'blind_review', 'repeat_policy', 'mode'}}
    data = dict(contract_version=prompt.VERSION, reference_case=case_contract, task=task_contract,
                rubric=rules, source_documents=manifest['source_documents'], **sources,
                candidate=candidate, output_shape=prompt.output_shape(case, task, candidate))
    if validation_feedback is not None:
        data['runtime_validation_feedback'] = validation_feedback
    return data


def repair_sources(paths, run_dir, run, tasks, inputs, manifest, cases, sources, config,max_protocol_repairs=1):
    """One explicit protocol repair, with mechanical feedback and no previous semantic scores."""
    if not paths:
        return {}
    require(type(max_protocol_repairs) is int and max_protocol_repairs in {1,2},'Protocol repair limit must be one or two')
    selected = {t['id']: t for t in tasks}
    repairs = {}
    for path in map(Path, paths):
        original = read_json(path)
        tid = original.get('task_id')
        require(tid in selected and tid not in repairs, 'Repair task is unselected or duplicated')
        require(original.get('status') in {'invalid_scorecard','api_failed'}, 'Only rejected or failed scorecards may be repaired')
        metadata_path = path.parent.parent / 'judge-run.json'
        contract = read_json(metadata_path)['contract']
        prior=contract.get('validation_repairs',{}).get(tid)
        transport_depth=0;protocol_depth=0
        if prior:
            if original['status']=='api_failed':
                transport_depth=prior.get('transport_retry_depth',1 if prior.get('retry_kind')=='transport' else 0)
                protocol_depth=prior.get('protocol_repair_depth',1 if prior.get('retry_kind','protocol')=='protocol' else 0)
                require(transport_depth<2,
                        'Only one explicit protocol repair is allowed by default; transport retries are bounded at two')
            else:
                protocol_depth=prior.get('protocol_repair_depth',1 if prior.get('retry_kind','protocol')=='protocol' else 0)
                transport_depth=prior.get('transport_retry_depth',1 if prior.get('retry_kind')=='transport' else 0)
                require(protocol_depth<max_protocol_repairs,
                        'Only one explicit protocol repair is allowed by default; configured limit reached')
        require(contract['run_sha256'] == digest(run_dir / 'run.json')
                and contract['source_run_id'] == run['run_id']
                and contract['dataset_manifest_sha256'] == run['dataset_manifest_sha256'], 'Repair source run mismatch')
        same_configuration=contract['judge']==config.public()
        if original['status']=='api_failed':
            same_configuration=({k:v for k,v in contract['judge'].items() if k!='timeout_seconds'}
                                =={k:v for k,v in config.public().items() if k!='timeout_seconds'}
                                and contract['judge']['timeout_seconds']<=config.timeout<=600)
        require(same_configuration
                and contract['prompt_sha256'] == hashlib.sha256(prompt.SYSTEM.encode()).hexdigest(),
                'Repair must retain the same judge configuration and scoring instructions')
        result_path, result = inputs[tid]
        require(contract['source_result_hashes'][tid] == digest(result_path), 'Repair source answer changed')
        task, case = selected[tid], cases[selected[tid]['case_id']]
        body = original.get('raw_response')
        if original['status']=='api_failed':
            previous_feedback=prior.get('feedback') if prior else None
            expected=sha(request_body(config,packet(case,task,result,manifest,sources,
                                                   read_json(run_dir/'dataset/rubric.json'),previous_feedback)))
            require(original['request_sha256']==expected,'Failed transport request fingerprint mismatch')
            repairs[tid]=dict(original_record_sha256=digest(path),original_metadata_sha256=digest(metadata_path),
                              original_review_run=path.parent.parent.name,retry_kind='transport',
                              transport_retry_depth=transport_depth+1,protocol_repair_depth=protocol_depth,
                              feedback=previous_feedback)
            continue
        require(isinstance(body, dict) and sha(body) == original['response_sha256'], 'Rejected response fingerprint mismatch')
        raw = None
        try:
            raw = strict_json(extract(body, config.api))
            validate_review(raw, case, task, result, result_path,
                            {d['id'] for d in manifest['source_documents']}, sources, config, {})
        except (ValueError, KeyError, TypeError, IndexError) as error:
            # These are local protocol failures, never a human-assigned quality diagnosis.
            reason = str(error) if type(error) is ValueError else type(error).__name__
        else:
            raise ValueError('Rejected scorecard now validates; inspect it before any paid replay')
        invalid_quotes = []
        actual_evidence = {e['ref']: e['text'] for e in result['response'].get('retrieved_evidence', [])}
        reference_text={e['id']:' '.join(part['quote'] for part in [e,*e.get('continuation',[])])
                        for e in sources['reference_evidence']}
        paper_text={p['document_id']:p['text'] for p in sources['paper_texts']}
        for claim in (raw or {}).get('claim_assessments', []):
            if not isinstance(claim, dict):
                continue
            for basis in claim.get('basis', []):
                if not isinstance(basis, dict):
                    continue
                kind=basis.get('type')
                table,ref=(actual_evidence,basis.get('ref')) if kind=='evidence' else \
                          (reference_text,basis.get('evidence_id')) if kind=='reference_evidence' else \
                          (paper_text,basis.get('document_id')) if kind=='paper_text' else ({},None)
                quote=basis.get('quote')
                if isinstance(quote,str) and isinstance(ref,str) and ref in table \
                        and normalized(quote) not in normalized(table[ref]):
                    fragments=[s for s in re.split(r'(?<=[.!?])\s+|\n',table[ref]) if s.strip() and len(s)<=2000]
                    invalid_quotes.append(dict(claim_id=claim.get('id'),source_kind=kind,ref=ref,rejected_quote=quote,
                                               exact_match_refs=[r for r,text in table.items() if normalized(quote) in normalized(text)],
                                               verbatim_source_fragments=difflib.get_close_matches(quote,fragments,n=3,cutoff=.15)))
        feedback = dict(kind='protocol_validation_only', error=reason, previous_scores_provided=False,
                        note='Generate a fresh complete scorecard from the same question, rubric and sources. '
                             'A format rejection is not evidence that the candidate answer is wrong. '
                             'Use scalar retrieval labels, copy quotes verbatim from the named source, '
                             'and include every applicable defect link. No prior scores or judgments are supplied.',
                        retrieval_allowed_values={k: (['not_applicable'] if value == 'not_applicable'
                                                       else ['complete', 'partial', 'missing'])
                                                  for k, value in prompt.retrieval_applicability(case, task).items()},
                        invalid_quote_locations=invalid_quotes)
        repairs[tid] = dict(original_record_sha256=digest(path), original_metadata_sha256=digest(metadata_path),
                            original_review_run=path.parent.parent.name,retry_kind='protocol',
                            protocol_repair_depth=protocol_depth+1,transport_retry_depth=transport_depth,
                            max_protocol_repairs=max_protocol_repairs,feedback=feedback)
    require(set(repairs) == set(selected), 'Repair selection must contain exactly the rejected tasks')
    return repairs


def request_body(config, data):
    messages = [{'role': 'system', 'content': prompt.SYSTEM}, {'role': 'user', 'content': encode(data)}]
    if config.api == 'responses':
        return dict(model=config.model, input=messages, max_output_tokens=config.max_output_tokens,
                    text={'format': {'type': 'json_object'}}, store=False)
    return dict(model=config.model, messages=messages, max_completion_tokens=config.max_output_tokens,
                response_format={'type': 'json_object'}, store=False)


def extract(body, mode):
    require(isinstance(body, dict), 'Invalid judge API response')
    if mode == 'responses':
        require(body.get('status') == 'completed', 'Judge response was not completed')
        chunks = [c['text'] for item in body.get('output', []) if item.get('type') == 'message'
                  for c in item.get('content', []) if c.get('type') == 'output_text']
        require(bool(chunks), 'Judge response has no text')
        return ''.join(chunks)
    choices = body.get('choices', [])
    require(len(choices) == 1 and choices[0].get('finish_reason') == 'stop', 'Judge chat response incomplete')
    content = choices[0].get('message', {}).get('content')
    require(isinstance(content, str) and bool(content), 'Judge response has no text')
    return content


def usage(body):
    raw = body.get('usage') or {}
    fields = {'input_tokens': ('input_tokens', 'prompt_tokens'),
              'output_tokens': ('output_tokens', 'completion_tokens'), 'total_tokens': ('total_tokens',)}
    return {k: next((raw[n] for n in names if type(raw.get(n)) is int and raw[n] >= 0), None)
            for k, names in fields.items()}


def strict_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'Duplicate judge JSON field')
            result[k] = v
        return result
    def constant(_):
        raise ValueError('Non-finite judge number')
    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    require(isinstance(result, dict), 'Judge scorecard must be an object')
    return result


def validate_review(raw, case, task, result, result_path, documents, sources, config, provenance,normalize_structure=False):
    expected = set(prompt.output_shape(case, task, result.get('response') or {}))
    require(set(raw) == expected, 'Judge scorecard fields missing or unexpected')
    require(isinstance(raw['reference_concerns'], list)
            and all(isinstance(s, str) and s.strip() for s in raw['reference_concerns']), 'Invalid reference concerns')
    review = dict(deepcopy(raw), task_id=task['id'], case_id=case['id'], run_id=result['run_id'],
                  response_file_sha256=digest(result_path), review_status='ai_source_reviewed',
                  reviewer=f'{config.model} via {urlsplit(config.base_url).hostname}', reviewer_type='ai',
                  reviewed_at=now(), participated_in_authoring=False, judge_provenance=provenance)
    review_task(case, task, result, review, result_path, documents, sources,normalize_structure)
    return review


@contextmanager
def lock(output):
    path = output / '.judge.lock'
    try:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError('Judge directory is locked; check for an active or interrupted process') from None
    try:
        yield
    finally:
        path.unlink()


def run_judge(run_dir, output, config, *, limit=1, task_ids=None, client=None, repair_records=None,max_protocol_repairs=1):
    run_dir, output = Path(run_dir).resolve(), Path(output).resolve()
    require(type(limit) is int and 1 <= limit <= 100, 'Judge task limit must be 1..100')
    # Results live in a separate review directory. Never write inside frozen dataset/results/historical reviews.
    require(output != run_dir and not output.is_relative_to(run_dir) and not run_dir.is_relative_to(output),
            'Judge output must be a separate directory outside source run')
    run, manifest, cases, sources = verify_run(run_dir)
    require(config.model != run.get('configuration', {}).get('llm_model'), 'Judge must use a different model from the answerer')
    selected = [t for t in run['tasks'] if task_ids is None or t['id'] in task_ids]
    require(bool(selected) and (task_ids is None or {t['id'] for t in selected} == set(task_ids)), 'Unknown/empty judge task selection')
    selected_inputs = {}
    for task in selected:
        path, result = read_result(run_dir, run, cases[task['case_id']], task)
        selected_inputs[task['id']] = (path, result)
    repairs = repair_sources(repair_records, run_dir, run, selected, selected_inputs, manifest, cases, sources, config,max_protocol_repairs)
    output.mkdir(parents=True, exist_ok=True)
    with lock(output):
        return _run(run_dir, output, config, limit, selected, selected_inputs,
                    run, manifest, cases, sources, client, repairs)


def _run(run_dir, output, config, limit, tasks, inputs, run, manifest, cases, sources, client, repairs):
    contract = dict(contract_version=prompt.VERSION, source_run_id=run['run_id'],
                    run_sha256=digest(run_dir / 'run.json'), dataset_manifest_sha256=run['dataset_manifest_sha256'],
                    task_ids=[t['id'] for t in tasks], source_result_hashes={k: digest(v[0]) for k, v in inputs.items()},
                    judge=config.public(), prompt_sha256=hashlib.sha256(prompt.SYSTEM.encode()).hexdigest(),
                    harness_files={n: digest(Path(__file__).with_name(n)) for n in HARNESS},
                    assessment_mode='independent_api_model_reference_review', previous_scores_in_prompt=False,
                    policy_note='Versioned judge adapter; original v2 material/manual policy is preserved unchanged.')
    if repairs:
        contract['validation_repairs'] = repairs
        contract['repair_policy'] = 'One explicit protocol regrade by default (two only if explicitly configured), or two explicit transport retries; same rubric/model/prompt; no previous semantic scores supplied. A longer network deadline does not change the API request.'
    metadata_path = output / 'judge-run.json'
    if metadata_path.exists():
        require(read_json(metadata_path)['contract'] == contract, 'Judge configuration, inputs or code changed; use a new output directory')
        require(all(digest(output / 'harness' / n) == value for n, value in contract['harness_files'].items()),
                'Archived judge harness changed')
    else:
        write(metadata_path, dict(created_at=now(), contract=contract))
        (output / 'harness').mkdir()
        for name in HARNESS:
            (output / 'harness' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    (output / 'tasks').mkdir(exist_ok=True)
    rubric = read_json(run_dir / 'dataset/rubric.json')
    documents = {d['id'] for d in manifest['source_documents']}
    owned = client is None
    client = client or httpx.Client(timeout=config.timeout, trust_env=False, follow_redirects=False)
    calls = 0
    reviews, records = [], []
    try:
        for task in tasks:
            tid = task['id']
            path, result = inputs[tid]
            record_path = output / 'tasks' / (tid + '.json')
            data = packet(cases[task['case_id']], task, result, manifest, sources, rubric,
                          repairs.get(tid, {}).get('feedback'))
            request = request_body(config, data)
            request_hash = sha(request)
            if record_path.exists():
                record = read_json(record_path)
                require(record['request_sha256'] == request_hash, 'Saved judge request changed')
                # pending/failed/invalid are never implicitly retried: a network timeout may still have been billed.
                if record['status'] == 'completed':
                    require(sha(record['raw_response']) == record['response_sha256'], 'Saved judge response changed')
                    raw = strict_json(extract(record['raw_response'], config.api))
                    rechecked = validate_review(raw, cases[task['case_id']], task, result, path,
                                               documents, sources, config, record['review']['judge_provenance'])
                    rechecked['reviewed_at'] = record['review']['reviewed_at']
                    require(rechecked == record['review'], 'Saved judge scorecard changed')
                    reviews.append(record['review'])
                records.append(record)
                continue
            if result['status'] == 'failed':
                record = dict(task_id=tid, status='answer_failed', request_sha256=request_hash, api_calls=0)
            elif calls >= limit:
                continue
            else:
                record = dict(task_id=tid, status='pending', started_at=now(), request_sha256=request_hash,
                              api_calls=1, usage=None, actual_charge=None)
                write(record_path, record)  # Persist before crossing network boundary.
                calls += 1
                start = time.monotonic()
                try:
                    suffix = '/responses' if config.api == 'responses' else '/chat/completions'
                    response = client.post(config.base_url + suffix, json=request,
                                           headers={'Authorization': 'Bearer ' + config.api_key})
                    record.update(http_status=response.status_code,
                                  duration_ms=round((time.monotonic() - start) * 1000),
                                  provider_request_id=(response.headers.get('x-request-id') or '').replace(config.api_key, '[REDACTED]') or None)
                    if not 200 <= response.status_code < 300:
                        record.update(status='api_failed', reason_code='http_' + str(response.status_code),
                                      error_body_sha256=hashlib.sha256(response.content).hexdigest())
                    else:
                        # Never persist authorization headers or a server echo of the secret.
                        raw_text = response.text.replace(config.api_key, '[REDACTED]')
                        body = strict_json(raw_text)
                        record.update(raw_response=body, response_sha256=sha(body), usage=usage(body),
                                      returned_model=body.get('model'), provider_response_id=body.get('id'))
                        record['status'] = 'invalid_scorecard'
                        provenance = dict(contract_version=prompt.VERSION, requested_model=config.model,
                                          returned_model=body.get('model'), base_url=config.base_url, api=config.api,
                                          request_sha256=request_hash, response_sha256=sha(body),
                                          prompt_sha256=contract['prompt_sha256'], provider_response_id=body.get('id'),
                                          provider_request_id=record['provider_request_id'],
                                          reference_concerns_unresolved=bool(body.get('reference_concerns')))
                        if tid in repairs:
                            provenance['validation_repair_of_sha256'] = repairs[tid]['original_record_sha256']
                        raw = strict_json(extract(body, config.api))
                        provenance['reference_concerns_unresolved'] = bool(raw.get('reference_concerns'))
                        review = validate_review(raw, cases[task['case_id']], task, result, path,
                                                 documents, sources, config, provenance)
                        record.update(status='completed', review=review)
                        reviews.append(review)
                except httpx.HTTPError as error:
                    record.update(status='api_failed', reason_code=type(error).__name__)
                except (ValueError, KeyError, TypeError, IndexError) as error:
                    record.update(status='invalid_scorecard', reason_code=type(error).__name__)
                    # Local validation errors only, never interpolate a provider-supplied JSON field or secret.
                    record['validation_error'] = 'Judge output did not satisfy the source-review contract'
                record.update(finished_at=now(), duration_ms=round((time.monotonic() - start) * 1000))
            write(record_path, record)
            records.append(record)
        reviews_file = output / 'reviews.jsonl'
        reviews_file.write_text(''.join(encode(r) + '\n' for r in reviews), encoding='utf-8')
        completed = sum(r['status'] == 'completed' for r in records)
        all_ready = len(records) == len(tasks) and all(r['status'] in {'completed', 'answer_failed'} for r in records)
        concerns = sum(bool(r.get('reference_concerns')) for r in reviews)
        totals = {k: sum((r.get('usage') or {}).get(k) or 0 for r in records)
                  for k in ('input_tokens', 'output_tokens', 'total_tokens')}
        known_calls = sum(all(type((r.get('usage') or {}).get(k)) is int for k in totals) for r in records)
        progress = dict(source_run_id=run['run_id'], requested_model=config.model,
                        selected_tasks=len(tasks), completed=completed, pending=len(tasks) - len(records),
                        statuses={s: sum(r['status'] == s for r in records) for s in sorted({r['status'] for r in records})},
                        api_calls_this_invocation=calls, recorded_api_calls=sum(r.get('api_calls', 0) for r in records),
                        usage_known_calls=known_calls, known_tokens=totals if known_calls else None,
                        actual_charge=None, charge_note='Third-party invoice not collected; tokens are not a billed amount.',
                        reference_concerns=concerns, complete=all_ready, summary_written=False,
                        human_calibration_status='not_performed', independent_of_answer_model=True,
                        provider_identity_note='Model identity is reported by the configured third-party gateway, not independently verified.')
        # No subset headline scores and no silent acceptance when the judge disputes a reference.
        if all_ready and {t['id'] for t in tasks} == {t['id'] for t in run['tasks']} and not concerns:
            summary = summarize(run_dir, reviews_file)
            progress['summary_written'] = True
            summary['independent_judge'] = dict(metadata_sha256=digest(metadata_path), **progress)
            write(output / 'summary.json', summary)
        write(output / 'progress.json', progress)
        return progress
    finally:
        if owned:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / 'backend/.env.judge')
    parser.add_argument('--limit', type=int, default=1, help='Maximum new paid requests; completed tasks are skipped')
    parser.add_argument('--task', action='append', help='Optional exact task selection; fixed for this review directory')
    parser.add_argument('--repair-record', action='append', type=Path,
                        help='Explicit rejected task record to regrade once, with machine validation feedback only')
    parser.add_argument('--max-protocol-repairs',type=int,choices=[1,2],default=1,
                        help='Explicit upper bound per task; only rejected outputs can be retried')
    args = parser.parse_args()
    try:
        result = run_judge(args.run_dir, args.output_dir, load_config(args.env_file),
                           limit=args.limit, task_ids=args.task, repair_records=args.repair_record,
                           max_protocol_repairs=args.max_protocol_repairs)
    except Exception as error:
        # Avoid echoing raw provider responses, config, or model-controlled exceptions.
        parser.exit(1, 'Independent judge operation failed: ' + type(error).__name__ + '\n')
    print(json.dumps(result, ensure_ascii=False))
    if not result['complete']:
        parser.exit(2)


if __name__ == '__main__':
    main()
