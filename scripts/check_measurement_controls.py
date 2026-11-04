"""Paid synthetic controls for measurement interpretation; not benchmark questions."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Use a new output directory; no implicit paid retry')
    from literature_rag.config import Settings
    from literature_rag.adapters.providers.evidence_review import DeepSeekEvidenceReviewer
    from literature_rag.application.evidence_review import EvidenceReviewService
    from literature_rag.domain.models import Evidence,GeneratedAnswer,GeneratedClaim
    settings=Settings(_env_file=ROOT/'backend/.env.literature')
    cases=[
        ('numeric','表中相对峰面积百分比是多少？',
         'The normalized peak area fraction is 25%.', '相对峰面积百分比为25%。'),
        ('absolute','这里的绝对浓度如何测定，数值是多少？',
         'The concentration was measured using a calibration curve against certified standards. '
         'The calibrated absolute concentration is 2.0 mg/L. It is not a normalized peak-area fraction.',
         '用有证标准品建立校准曲线，测得的绝对浓度为2.0 mg/L。'),
    ]
    args.output.mkdir(parents=True)
    for name,question,source,text in cases:
        es=[Evidence('[1]','synthetic','synthetic','synthetic-control.txt',1,1,source,1.)]
        draft=GeneratedAnswer(text+' [1]',(GeneratedClaim(text,('[1]',)),))
        p=DeepSeekEvidenceReviewer(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
            thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
            timeout_seconds=settings.evidence_review_timeout_seconds,max_output_tokens=settings.evidence_review_max_output_tokens,
            diagnostic=True,diagnosis_version='v2_measurement',diagnostics_dir=args.output/'private-diagnostics')
        service=EvidenceReviewService(p)
        final=service.review(question,es,draft)
        result=dict(synthetic=True,question=question,source=source,draft=asdict(draft),final=asdict(final),trace=service.last_trace)
        (args.output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(case=name,status=service.last_trace['status'],unchanged=final==draft)),flush=True)


if __name__=='__main__':main()
