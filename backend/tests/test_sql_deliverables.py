import pytest

from literature_rag.application.planner_inputs import InputSelection, select_evidence
from literature_rag.application.task_coverage import Requirement, CoverageItem, ground_requirements, coverage_report


QUESTION='有多少个数据块、多少个数据块×循环组合'
SUMMARY='fiber.v_recycled_cycle_summary'
DETAIL='fiber.v_recycled_cycle_detail'


def need(keys, **changes):
    metric=dict(population='recycled',operation='count',keys=keys,**changes)
    return Requirement(role='sql',source_quote=QUESTION,metric=metric)


def snapshot(query, columns, rows):
    return dict(request=dict(tool='query_experiment_data'),model_delivery=dict(status='delivered'),
                result=dict(status='completed',result=dict(ref='[15]',sql=query,columns=columns,rows=rows,row_count=len(rows))))


def grade(requirements, events, claims, inherited=False):
    reqs,_=ground_requirements(requirements,QUESTION)
    items=[CoverageItem(requirement_id=req['requirement_id'],status='verified',refs=['[15]'],
                        finding='测试',cells=cells) for req,cells in zip(reqs,claims)]
    return coverage_report(reqs,items,{'inherited_tool_calls' if inherited else 'tool_calls':events})


def cell(column,value,row=0):
    return dict(ref='[15]',row=row,column=column,value=value)


def test_old_summary_snapshot_cannot_verify_both_atomic_counts():
    event=snapshot(f'SELECT COUNT(*) AS n_block_cycle_rows, SUM(replicate_count) AS n_raw_rows FROM {SUMMARY}',
                   ['n_block_cycle_rows','n_raw_rows'],[[47,131]])
    choice=InputSelection(source_child_id='sql',ref='[15]',columns=['n_block_cycle_rows'],row_indices=[0])
    inherited=select_evidence(event,'[15]',choice)
    requirements=[need(['数据块']),need(['数据块','循环'])]
    report=grade(requirements,[inherited],[[cell('n_block_cycle_rows',47)]]*2,inherited=True)
    assert [r['status'] for r in report['items']]==['missing','verified']
    assert not report['complete']


def test_one_query_can_supply_two_distinct_counts():
    event=snapshot(f'SELECT COUNT(DISTINCT block_code) a, COUNT(DISTINCT (block_code,cycle_no)) b FROM {DETAIL}',
                   ['a','b'],[[14,47]])
    assert grade([need(['block_code']),need(['block_code','cycle_no'])],[event],
                 [[cell('a',14)],[cell('b',47)]])['complete']


@pytest.mark.parametrize('query,value',[
    (f'SELECT COUNT(*) block_count FROM {DETAIL}',14),
    (f'SELECT COUNT(DISTINCT block_code) block_count FROM {DETAIL} WHERE cycle_no=1',14),
    (f'SELECT COUNT(DISTINCT block_code) block_count FROM {DETAIL}',13),
    (f'SELECT COUNT(DISTINCT block_code) block_count FROM {DETAIL} JOIN {SUMMARY} USING(block_code)',14),
])
def test_alias_population_filter_complex_scope_and_wrong_value_cannot_pass(query,value):
    assert not grade([need(['block_code'])],[snapshot(query,['block_count'],[[14]])],[[cell('block_count',value)]])['complete']


def test_grouped_subquery_and_freshness():
    query=f'SELECT COUNT(*) n FROM (SELECT block_code, cycle_no FROM {DETAIL} GROUP BY block_code,cycle_no) s'
    event=snapshot(query,['n'],[[47]])
    reqs,_=ground_requirements([need(['block_code','cycle_no'])],QUESTION)
    reqs[0]['fresh_query']=True
    item=CoverageItem(requirement_id='need_1',status='verified',finding='47',refs=['[15]'],cells=[cell('n',47)])
    assert not coverage_report(reqs,[item],dict(inherited_tool_calls=[event]))['complete']
    assert coverage_report(reqs,[item],dict(tool_calls=[event]))['complete']


def test_grouped_count_requires_all_groups_and_visible_group_keys():
    event=snapshot('SELECT sample_type, COUNT(*) n FROM fiber.v_sample_overview GROUP BY sample_type',
                   ['sample_type','n'],[['blend',9],['hardwood',24],['softwood',28]])
    req=Requirement(role='sql',source_quote=QUESTION,metric=dict(population='samples',operation='count',
                    keys=['规范样本'],group_by=['样本类型']))
    cells=[cell('n',v,i) for i,v in enumerate([9,24,28])]
    assert grade([req],[event],[cells])['complete']
    assert not grade([req],[event],[cells[:1]])['complete']
    event['model_delivery']['status']='withheld'
    assert not grade([req],[event],[cells])['complete']
