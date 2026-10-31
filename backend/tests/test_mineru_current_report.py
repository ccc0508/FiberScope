from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from report_mineru_current_20261101 import paired_ids,usage_summary


def test_paired_subset_keeps_valid_zero_and_excludes_missing_or_flagged_reviews():
    current={'a':{'reference_concern':False,'point_mean':0},'b':{'reference_concern':True},'c':{'reference_concern':False}}
    baseline={'a':{'reference_concern':False},'b':{'reference_concern':False},'d':{'reference_concern':False}}
    assert paired_ids(current,baseline)==['a']


def test_usage_never_adds_reasoning_twice_or_treats_unknown_as_known_zero():
    totals=usage_summary([{'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30,'reasoning_tokens':15}},
        {'usage':None},{'usage':{'input_tokens':7,'output_tokens':0}}])
    assert totals=={'calls':3,'known_tokens':{'input_tokens':17,'output_tokens':20,'total_tokens':30},'total_token_unknown_calls':2}
