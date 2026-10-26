"""Dedicated OpenRouter GPT-6 Luna credentials; reuse the frozen v3 scoring engine."""
from __future__ import annotations

import argparse
from decimal import Decimal
import math
import os
from pathlib import Path

from dotenv import dotenv_values

import judge_qa_eval as judge
import qa_scoring_policy as policy

MODEL = 'openai/gpt-6-luna'
BASE_URL = 'https://openrouter.ai/api/v1'
VERSION = 'qa-luna-openrouter-v1'


def load_config(path, *, require_key=True):
    judge.require(path.is_file(), 'Luna configuration file is missing')
    values = dotenv_values(path, interpolate=False)
    def get(name, default=''):
        key = 'QA_LUNA_' + name
        return (os.environ.get(key, values.get(key, default)) or '').strip()
    base = get('BASE_URL', BASE_URL).rstrip('/')
    model = get('MODEL', MODEL)
    judge.require(base == BASE_URL and model == MODEL, 'Use the pinned OpenRouter GPT-6 Luna model and endpoint')
    judge.require(get('API', 'chat_completions') == 'chat_completions', 'Luna adapter requires explicit chat_completions')
    key = get('API_KEY')
    judge.require(bool(key) or not require_key, 'Dedicated QA_LUNA_API_KEY is not configured')
    timeout = float(get('TIMEOUT_SECONDS', '180'))
    tokens = int(get('MAX_OUTPUT_TOKENS', '16000'))
    judge.require(math.isfinite(timeout) and 1 <= timeout <= 600 and 256 <= tokens <= 64000, 'Invalid Luna request limits')
    return judge.Config(base, model, key, 'chat_completions', timeout, tokens)


def prepare(run_dir, config, task_ids=None):
    """Build all inputs without credentials, network access or output-directory writes."""
    run_dir = Path(run_dir)
    source, manifest, cases, sources = judge.verify_run(run_dir)
    tasks = [t for t in source['tasks'] if task_ids is None or t['id'] in task_ids]
    judge.require(tasks and (task_ids is None or set(task_ids) == {t['id'] for t in tasks}), 'Unknown Luna task selection')
    hashes = {}
    for task in tasks:
        _, result = judge.read_result(run_dir, source, cases[task['case_id']], task)
        judge.require(result['status'] != 'failed', 'Cannot grade a failed source answer')
        packet = judge.packet(cases[task['case_id']], task, result, manifest, sources,
                              judge.read_json(run_dir / 'dataset/rubric.json'))
        request = judge.request_body(config, packet)
        hashes[task['id']] = judge.sha(request)
    return dict(adapter_version=VERSION, requested_model=MODEL, api_base_url=BASE_URL,
                scoring_policy_version=policy.VERSION, scoring_policy_sha256=policy.SHA256,
                source_run_id=source['run_id'], source_run_sha256=judge.digest(run_dir / 'run.json'),
                prepared_tasks=len(tasks), request_sha256=hashes, model_calls=0,
                credential_configured=bool(config.api_key), paid_validation_performed=False)


def cost_summary(output):
    rows = []
    for path in sorted((Path(output) / 'tasks').glob('*.json')):
        record = judge.read_json(path)
        if not record.get('api_calls', 0):
            continue
        value = ((record.get('raw_response') or {}).get('usage') or {}).get('cost')
        cost = value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
        rows.append(dict(task_id=record['task_id'], status=record['status'],
                         api_calls=record['api_calls'], reported_cost_usd=cost))
    return dict(currency='USD', application_calls=sum(r['api_calls'] for r in rows),
                reported_cost_usd=str(sum((Decimal(str(r['reported_cost_usd'])) for r in rows
                                          if r['reported_cost_usd'] is not None), Decimal(0))),
                cost_known_calls=sum(r['api_calls'] for r in rows if r['reported_cost_usd'] is not None),
                cost_unknown_calls=sum(r['api_calls'] for r in rows if r['reported_cost_usd'] is None),
                actual_invoice_cost=None, rows=rows,
                note='Sum of known API-reported charges only; missing usage/cost is unknown, not free.')


def run(run_dir, output, config, *, limit=1, task_ids=None, client=None):
    judge.require(config.base_url == BASE_URL and config.model == MODEL
                  and config.api == 'chat_completions' and bool(config.api_key), 'Invalid dedicated Luna configuration')
    result = judge.run_judge(run_dir, output, config, limit=limit, task_ids=task_ids, client=client)
    costs = cost_summary(output)
    judge.write(Path(output) / 'openrouter-costs.json', costs)
    return dict(result, openrouter_costs=costs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--env-file', type=Path, default=judge.ROOT / 'backend/.env.luna')
    parser.add_argument('--limit', type=int, default=1)
    parser.add_argument('--task', action='append')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        config = load_config(args.env_file, require_key=not args.dry_run)
        if args.dry_run:
            result = prepare(args.run_dir, config, args.task)
        else:
            judge.require(args.output_dir is not None, 'A separate Luna output directory is required')
            result = run(args.run_dir, args.output_dir, config, limit=args.limit, task_ids=args.task)
    except Exception as error:
        parser.exit(1, 'Luna judge preparation/evaluation failed: ' + type(error).__name__ + '\n')
    print(judge.encode(result))


if __name__ == '__main__':
    main()
