"""Offline tests for the experimental bypass boundary; never calls providers."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import qa_unchecked_e2e_worker as w

class UncheckedTests(unittest.TestCase):
    def test_overrides_are_only_active_during_worker_execution(self):
        reviewer = w.provider.DeepSeekEvidenceReviewer
        service = w.corrective_review.CorrectiveReviewService

        def bindings():
            return (w.contract.parse_response, reviewer._complete_comparisons,
                    w.answer_question.CitationValidator, service.review)

        original = bindings()
        self.assertIsNot(original[0], w.parse_raw)
        self.assertIsNot(original[2], w.UncheckedSerializer)
        self.assertIsNot(original[3], w.unchecked_review)

        def fail_inside_worker():
            self.assertIs(w.contract.parse_response, w.parse_raw)
            self.assertIsNot(reviewer._complete_comparisons, original[1])
            self.assertIs(w.answer_question.CitationValidator, w.UncheckedSerializer)
            self.assertIs(service.review, w.unchecked_review)
            raise RuntimeError('simulated worker failure')

        worker = SimpleNamespace(run_cli=fail_inside_worker)
        with patch.dict(sys.modules, {'literature_worker': worker}):
            with self.assertRaisesRegex(RuntimeError, 'simulated worker failure'):
                w.main()
        self.assertEqual(bindings(), original)

    def test_accepts_unknown_review_fields_and_labels(self):
        p=w.parse_raw('{"issues":[],"units":"invalid","type":"unexpected"}')
        self.assertEqual(p.raw['units'],'invalid')

    def test_applies_wrong_anchor_and_unknown_citation_without_content_gate(self):
        c,e=w.apply_unchecked([dict(text='original',citation_refs=['[1]'])],[dict(claim_index=0,
            original_text='does not match',replacement_claims=[dict(text='edited [99]',citation_refs=['[99]'])])])
        self.assertEqual(c[0]['text'],'edited [99]')
        d=w.GeneratedAnswer('edited [99]',(w.GeneratedClaim('edited [99]',('[99]',)),))
        result=w.UncheckedSerializer().validate(d,[])
        self.assertEqual(result.answer,'edited [99]');self.assertEqual(result.citations,())

    def test_impossible_index_is_logged(self):
        c,e=w.apply_unchecked([dict(text='original',citation_refs=[])],[dict(claim_index=9,replacement_claims=[])])
        self.assertEqual(c[0]['text'],'original');self.assertEqual(e[0]['status'],'unexecutable_index')

    def test_review_failure_preserves_latest_answer_and_trace(self):
        class Provider:
            last_usage=None;last_model_info=None;last_api_calls=1;last_latency_ms=1
            last_http_status=None;last_failure_code='review_response_invalid'
            def review(self,*a,**k):raise ValueError('bad json')
        service=SimpleNamespace(reviewer=SimpleNamespace(provider=Provider()),reader=None)
        draft=w.GeneratedAnswer('original',(w.GeneratedClaim('original',('[1]',)),))
        self.assertEqual(w.unchecked_review(service,'q',[],draft),draft)
        self.assertEqual(service.last_trace['status'],'incomplete')
        self.assertEqual(service.last_trace['api_calls'],1)

if __name__=='__main__':unittest.main()
