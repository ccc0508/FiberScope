"""Submit a PDF, wait for saved candidate records, optionally evaluate a reference."""
import argparse
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--page', type=int, required=True)
    parser.add_argument('--table', required=True)
    parser.add_argument('--crop', help='Optional x0,top,x1,bottom in PDF points.')
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'tmp/literature-extraction')
    parser.add_argument('--benchmark', type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    params = {'page': args.page, 'table': args.table, 'request_id': str(uuid4()), 'filename': args.pdf.name}
    if args.crop:
        params['crop'] = args.crop
    base = args.base_url.rstrip('/') + '/api/v1/literature/extractions'
    with httpx.Client(timeout=30) as client:
        response = client.post(base, params=params, content=args.pdf.read_bytes(), headers={'Content-Type': 'application/pdf'})
        response.raise_for_status()
        task = response.json()
        print('Task accepted:', task['id'])
        deadline = monotonic() + 330
        while task['status'] == 'processing':
            if monotonic() > deadline:
                raise SystemExit('Client wait ended; the accepted task remains on the server.')
            sleep(1)
            response = client.get(base + '/' + task['id'])
            response.raise_for_status()
            task = response.json()
        output = args.output_dir / (task['id'] + '.json')
        output.write_text(json.dumps(task, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('Saved:', output)
        if args.benchmark:
            from literature_extraction_eval import evaluate
            report = evaluate(task, args.benchmark)
            report_path = args.output_dir / (task['id'] + '.eval.json')
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({k: report[k] for k in ('model', 'reference_measurements', 'candidate_measurements', 'correct_measurements', 'missing_count', 'unexpected_count', 'incorrect_count', 'precision', 'recall')}, ensure_ascii=False))
        if task['status'] != 'completed':
            raise SystemExit(f"Extraction failed: {task['reason_code']} ({task['message']})")


if __name__ == '__main__':
    main()
