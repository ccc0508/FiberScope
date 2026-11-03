"""Three predeclared paired replays on five development cases, no answer selection."""
import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / '.rag-data/evaluations/minimal-revision-paired-20261103'
CASES = ['PFI2-018', 'PFI2-024', 'PFI2-031', 'PFI2-023', 'PFI2-032']
SOURCE = ROOT / '.rag-data/evaluations/pfi-answer-deepseek-20261102/results'
LIBRARY = ROOT / '.rag-data/index-versions/mineru-qwen3-vl-images-20261102'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    if STUDY.exists():
        raise ValueError('Study already exists: inspect/resume saved attempts explicitly, never overwrite')
    STUDY.mkdir(parents=True)
    plan = [dict(repeat=r, version=v, directory=f'{r}-{v}') for r in (1, 2, 3)
        for v in (('v2', 'v3') if r % 2 else ('v3', 'v2'))]
    source_files = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / 'backend/literature_rag').rglob('*.py')}
    write(STUDY / 'plan.json', dict(cases=CASES, attempts=plan, source_files=source_files,
        source_answer_hashes={c: sha256((SOURCE / (c+'.json')).read_bytes()).hexdigest() for c in CASES},
        frozen_initial_answers=True, repeats_per_arm=3, no_gold_in_answer_context=True,
        comparison='v2.1 vs opt-in v3 minimal revision policy plus same-call proposal gate',
        tests_are_reused_development_cases=True, deployment=False,
        endpoints_not_independent_verifiers=True, no_seed_or_determinism_claim=True,
        quality_checks=['measurement boundary omission', 'unsupported factor ranking',
            'new causal direction', 'two-source conflict citation regression'],
        automatic_answer_retries=0, judge='separate Jev plus attributed source audit'))
    snapshot = STUDY / 'runtime'
    for relative in source_files:
        dest = snapshot / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / relative).read_bytes())
    for attempt in plan:
        assert all(sha256((ROOT / p).read_bytes()).hexdigest()==h for p,h in source_files.items())
        out = STUDY / attempt['directory']
        print(json.dumps(dict(starting=attempt)), flush=True)
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT/'scripts/check_corrective_review.py'),
            '--version', attempt['version'], '--results-dir', str(SOURCE), '--case-ids', *CASES,
            '--library', str(LIBRARY), '--output', str(out)], cwd=ROOT)
        if result.returncode:
            raise RuntimeError(f'Attempt {attempt["directory"]} failed; saved files retained')
        summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
        if len(summary)!=len(CASES) or any(x['status']=='harness_failed' for x in summary):
            raise RuntimeError('Incomplete attempt; no automatic paid retry')
        print(json.dumps(dict(completed=attempt)), flush=True)
    write(STUDY/'completed.json', dict(attempts=6, answers=30))


if __name__ == '__main__':
    main()
