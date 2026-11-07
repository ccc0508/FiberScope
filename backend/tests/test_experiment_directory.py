import pytest
from app.experiment_directory import describe, column_info, selection
from literature_rag.application.tools import INPUT

def test_directory_needs_no_column_or_enum_queries():
    class NoQuery:
        def execute(self,*a):pytest.fail('compact directory must not query rows')
    r=describe(NoQuery())
    assert len(r['views'])==8 and r['mode']=='directory'
    assert all('columns' not in v for v in r['views'].values())

def test_selection_and_schema():
    assert selection(['v_beating_analysis','fiber.v_beating_analysis'])==['v_beating_analysis']
    with pytest.raises(ValueError):selection(['pg_catalog.pg_tables'])
    assert INPUT.validate_python(dict(tool='describe_experiment_data',reason='test')).views is None

def test_semantics_are_view_specific():
    assert column_info('v_beating_analysis','fiber_length_weighted_mm','numeric')['unit']=='mm'
    assert '不是' in column_info('v_beating_analysis','beating_revolutions','integer')['description']
    assert '原始观测行数' in column_info('v_recycled_cycle_summary','replicate_count','smallint')['description']
    assert '纸张' in column_info('v_blend_analysis','replicate_count','smallint')['description']
    assert column_info('v_blend_analysis','new_unknown','text')['semantic_status']=='unconfirmed'

def test_details_only_actual_columns_and_live_values():
    class Result:
        def __init__(self,rows):self.rows=rows
        def fetchall(self):return self.rows
        def fetchone(self):return self.rows[0]
    class DB:
        def execute(self,q,args=None):
            if isinstance(q,str):return Result([('v_beating_analysis','material_code','text'),('v_beating_analysis','beating_revolutions','integer')])
            s=q.as_string()
            if 'EXISTS' in s:return Result([(True,)])
            if 'material_code,beating_revolutions' in s:return Result([('SW',4000),('HW',2000)])
            if '"material_code"' in s:return Result([('SW',),(None,)])
            return Result([(4000,),(None,)])
    r=describe(DB(),['v_beating_analysis'])
    assert list(r['views'])==['fiber.v_beating_analysis']
    v=r['views']['fiber.v_beating_analysis'];assert len(v['columns'])==2
    assert v['columns'][0]['enum']==dict(values=['SW'],has_null=True,truncated=False,limit=200,labels={'SW':'针叶木'})
    assert v['beating_levels_by_material']['rows']==[['SW',4000],['HW',2000]]
    assert not any('百分比' in n or '再生' in n or '透气' in n for n in r['notes'])
    assert 'notes' not in v


def test_notes_follow_field():
    assert 'unit_note' not in column_info('v_fiber_paper_analysis','tensile_index','numeric')
    assert '10%' in column_info('v_fiber_paper_analysis','fines_length_pct','numeric')['unit_note']
    assert '暂定' in column_info('v_fiber_paper_analysis','air_permeability','numeric')['unit_note']
    assert '未确认' in column_info('v_fiber_paper_analysis','folding_endurance_raw','numeric')['unit_note']


def test_recycled_notes_are_scoped_to_selected_view():
    class DB:
        def execute(self,*args):return self
        def fetchall(self):return [('v_recycled_cycle_detail','fiber_length_weighted_mm','numeric')]
    r=describe(DB(),['v_recycled_cycle_detail'])
    assert any('处理条件未知' in n for n in r['views']['fiber.v_recycled_cycle_detail']['notes'])
    assert all('再生' not in n and '异常' not in n for n in r['notes'])
