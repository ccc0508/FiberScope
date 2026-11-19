import sqlite3

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


@pytest.mark.parametrize('other_value,unit,code,expected', [
    (0.5,'mg/m','A',None), (0.4,'mg/m','A','numeric_corroboration_value_mismatch'),
    (0.5,'mg/100m','A','numeric_corroboration_unit_mismatch'),
    (0.5,'mg/m','B','numeric_corroboration_scope_mismatch'),
])
def test_corroborating_sample_measurement(other_value,unit,code,expected):
    from literature_rag.application.sql_deliverables import verify_metric
    col='fiber_coarseness_mg_m'
    def measurement(view,ref,code,value,unit):
        e=snapshot(f"SELECT {col} FROM fiber.{view} WHERE canonical_code='{code}'",[col],[[value]])
        e['result']['result'].update(ref=ref,column_metadata=[dict(name=col,unit=unit)])
        return e
    req=dict(metric=dict(population='samples',operation='value',keys=[col],group_by=[],equals={'canonical_code':'A'}))
    primary=cell(col,0.5)
    secondary=dict(primary,ref='[16]',value=other_value)
    trace=dict(tool_calls=[measurement('v_fiber_paper_analysis','[15]','A',0.5,'mg/m'),
                           measurement('v_blend_analysis','[16]',code,other_value,unit)])
    for fields in [dict(cells=[primary,secondary]), dict(cells=[primary],corroborating_cells=[secondary])]:
        assert verify_metric(req,dict(refs=['[15]','[16]'],**fields),trace)==expected


@pytest.mark.parametrize('operation', ['avg', 'sum', 'min', 'max'])
@pytest.mark.parametrize('inherited', [False, True])
def test_summary_measurements_cannot_certify_raw_observation_aggregates(operation, inherited):
    # Unequal replicate counts make the mean of block/cycle means differ from
    # the overall raw mean; the other aggregates also change after summarizing.
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE observations (block_code TEXT, cycle_no INT, fiber_length_weighted_mm REAL)')
        db.executemany('INSERT INTO observations VALUES (?, ?, ?)',
                       [('A', 1, 1), ('A', 1, 9), ('B', 1, 99), ('B', 1, 101), ('B', 1, 100)])
        raw = db.execute(f'SELECT {operation}(fiber_length_weighted_mm) FROM observations').fetchone()[0]
        summary = db.execute(f'SELECT {operation}(mean) FROM '
                             '(SELECT AVG(fiber_length_weighted_mm) mean FROM observations '
                             'GROUP BY block_code, cycle_no)').fetchone()[0]
    assert raw != summary
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='recycled', operation=operation, keys=['fiber_length_weighted_mm']))
    for view, value, expected in [(DETAIL, raw, True), (SUMMARY, summary, False)]:
        event = snapshot(f'SELECT {operation}(fiber_length_weighted_mm) n FROM {view}', ['n'], [[value]])
        if inherited:
            choice = InputSelection(source_child_id='sql', ref='[15]', columns=['n'], row_indices=[0])
            event = select_evidence(event, '[15]', choice)
        report = grade([req], [event], [[cell('n', value)]], inherited=inherited)
        assert report['complete'] is expected


def test_summary_measurement_value_cannot_certify_raw_value():
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='recycled', operation='value', keys=['fiber_length_weighted_mm'],
        equals=dict(block_code='A', cycle_no='1')))
    event = snapshot(f"SELECT fiber_length_weighted_mm n FROM {SUMMARY} WHERE block_code='A' AND cycle_no=1",
                     ['n'], [[5]])
    assert not grade([req], [event], [[cell('n', 5)]])['complete']


def test_summary_grouped_counts_keep_natural_group_keys():
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='recycled', operation='count', keys=['block_code', 'cycle_no'], group_by=['block_code']))
    event = snapshot(f'SELECT block_code, COUNT(*) n FROM {SUMMARY} GROUP BY block_code',
                     ['block_code', 'n'], [['A', 2], ['B', 3]])
    assert grade([req], [event], [[cell('n', 2, 0), cell('n', 3, 1)]])['complete']


@pytest.mark.parametrize('keys,groups,filters,query', [
    (['fiber_length_weighted_mm'], [], {}, 'SELECT COUNT(DISTINCT fiber_length_weighted_mm) n'),
    (['block_code'], [], {'fiber_length_weighted_mm': '5'},
     'SELECT COUNT(DISTINCT block_code) n'),
    (['block_code'], ['fiber_length_weighted_mm'], {},
     'SELECT fiber_length_weighted_mm, COUNT(DISTINCT block_code) n'),
])
def test_summary_measurement_counts_filters_and_groups_are_not_raw_scope(keys, groups, filters, query):
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='recycled', operation='count', keys=keys, group_by=groups, equals=filters))
    query += f' FROM {SUMMARY}'
    if filters:
        query += ' WHERE fiber_length_weighted_mm=5'
    if groups:
        query += ' GROUP BY fiber_length_weighted_mm'
    event = snapshot(query, ['fiber_length_weighted_mm', 'n'] if groups else ['n'],
                     [[5, 1]] if groups else [[1]])
    assert not grade([req], [event], [[cell('n', 1)]])['complete']


@pytest.mark.parametrize('inherited', [False, True])
@pytest.mark.parametrize('actual,claimed,expected', [
    (None, None, True), (None, 0, False), (0, None, False), (None, 'NULL', False), (0, 0, True),
])
def test_null_aggregate_matches_only_json_null(actual, claimed, expected, inherited):
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='samples', operation='avg', keys=['fiber_length_weighted_mm'],
        equals=dict(canonical_code='NO_SUCH_SAMPLE')))
    event = snapshot("SELECT AVG(fiber_length_weighted_mm) n FROM fiber.v_fiber_paper_analysis "
                     "WHERE canonical_code='NO_SUCH_SAMPLE'", ['n'], [[actual]])
    if inherited:
        choice = InputSelection(source_child_id='sql', ref='[15]', columns=['n'], row_indices=[0])
        event = select_evidence(event, '[15]', choice)
    report = grade([req], [event], [[cell('n', claimed)]], inherited=inherited)
    assert report['complete'] is expected


def test_null_still_requires_matching_query_scope():
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='samples', operation='avg', keys=['fiber_length_weighted_mm'],
        equals=dict(canonical_code='NO_SUCH_SAMPLE')))
    event = snapshot('SELECT AVG(fiber_length_weighted_mm) n FROM fiber.v_fiber_paper_analysis', ['n'], [[None]])
    assert not grade([req], [event], [[cell('n', None)]])['complete']


def test_grouped_aggregate_can_include_null_and_zero():
    req = Requirement(role='sql', source_quote=QUESTION, metric=dict(
        population='samples', operation='avg', keys=['fiber_length_weighted_mm'], group_by=['sample_type']))
    event = snapshot('SELECT sample_type, AVG(fiber_length_weighted_mm) n '
                     'FROM fiber.v_fiber_paper_analysis GROUP BY sample_type',
                     ['sample_type', 'n'], [['hardwood', None], ['softwood', 0]])
    assert grade([req], [event], [[cell('n', None, 0), cell('n', 0, 1)]])['complete']
