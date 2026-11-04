"""Paid synthetic interpretation controls; not benchmark questions."""
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
    parser.add_argument('--suite',choices=['measurement','ranking','unified'],default='measurement')
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
    if args.suite=='ranking':
        cases=[
            ('association','WRV和结合强度有什么联系？',
             'WRV was positively associated with bonding strength in this experiment.',
             '本实验中WRV与结合强度正相关。'),
            ('numeric','哪个样本的长度数值更大？',
             'The measured length of sample A is 3 mm and sample B is 2 mm.',
             '样本A长度3 mm，样本B长度2 mm，A的长度数值更大。'),
            ('supported','这三个因素哪个与Y的相关性最强？',
             'In the same experiment, the Pearson correlations with Y were A: 0.8, B: 0.5, C: 0.2. '
             'A had the strongest correlation. These correlations do not establish causal contribution.',
             '本实验按Pearson相关系数比较，A为0.8、B为0.5、C为0.2，A与Y的相关性最强；这不代表A的因果贡献最大。'),
        ]
    if args.suite=='unified':
        cases=[
            ('numeric','哪个样本长度更大？','Sample A has a length of 3 mm. Sample B has a length of 2 mm.',
             '样本A为3 mm，样本B为2 mm，A的长度更大。'),
            ('implicit_scope','这个结论适用于哪些材料？',
             'The observations were obtained only from bleached softwood kraft pulp under the stated experimental conditions. '
             'No other materials were tested.',
             '这一结论适用于所有植物纤维材料。'),
            ('supported_cause','请解释加热的两个结果。',
             'Under the tested conditions, heating causes expansion and softening.',
             '在该实验条件下，加热导致膨胀和软化。'),
        ]
    args.output.mkdir(parents=True)
    for name,question,source,text in cases:
        es=[Evidence('[1]','synthetic','synthetic','synthetic-control.txt',1,1,source,1.)]
        draft=GeneratedAnswer(text+' [1]',(GeneratedClaim(text,('[1]',)),))
        p=DeepSeekEvidenceReviewer(settings.llm_model,settings.llm_api_key.get_secret_value(),settings.llm_base_url,
            thinking_enabled=settings.llm_thinking_enabled,reasoning_effort=settings.llm_reasoning_effort,
            timeout_seconds=settings.evidence_review_timeout_seconds,max_output_tokens=settings.evidence_review_max_output_tokens,
            diagnostic=True,diagnosis_version={'ranking':'v2_ranking','measurement':'v2_measurement','unified':'v3_unified'}[args.suite],
            diagnostics_dir=args.output/'private-diagnostics')
        service=EvidenceReviewService(p)
        final=service.review(question,es,draft)
        result=dict(synthetic=True,question=question,source=source,draft=asdict(draft),final=asdict(final),trace=service.last_trace)
        (args.output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(case=name,status=service.last_trace['status'],unchanged=final==draft)),flush=True)


if __name__=='__main__':main()
