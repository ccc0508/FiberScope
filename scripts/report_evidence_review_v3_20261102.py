"""Run the same offline report and validation for the separately sealed v3 experiment."""
import sys

import report_evidence_review_20261102 as report
import evaluate_evidence_review_v3_20261102 as experiment
import judge_qa_eval as judge
from validate_qa_eval import require

report.OUTPUT=experiment.OUTPUT
report.RUN=experiment.RUN
report.verify=experiment.verify
report.PUBLIC=experiment.ROOT/'data/literature/qa-evaluation/reports/evidence-review-20261102-v3'
report.ADJUDICATION=experiment.OUTPUT/'codex-adjudication.json'


if __name__=='__main__':
    require(len(sys.argv)==2 and sys.argv[1] in {'packets','publish'},'Choose packets or publish')
    print(judge.encode(report.packets() if sys.argv[1]=='packets' else report.publish()))
