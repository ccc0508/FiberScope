"""Five independent real-model smoke cases; reference queries never enter model context."""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.experiment_sql import connect

CASES=[
 dict(id='SQL01', question='只查平台实验数据库：纤维长度有哪两种口径，字段名和单位分别是什么？再按样本类型统计规范样本数及总数。不要把实验展示行数当样本数，不要检索论文。',
 sql='SELECT sample_type,COUNT(*) AS n FROM fiber.v_sample_overview GROUP BY sample_type ORDER BY sample_type',
 criteria='目录说明算术平均/长度加权，均为mm；blend9/hardwood24/softwood28，总61；实际查库，有数据引用。'),
 dict(id='SQL02', question='查询针叶木浆打浆转数在4000到8000转之间（包含两端）的实验记录，列出实验编号、样本编号、转数、长度加权纤维长度和抗张指数，按转数、实验编号排序，注明单位。不需要论文解释。',
 sql="SELECT experiment_code,canonical_code,beating_revolutions,fiber_length_weighted_mm,tensile_index FROM fiber.v_beating_analysis WHERE material_code='SW' AND beating_revolutions BETWEEN 4000 AND 8000 ORDER BY beating_revolutions,experiment_code",
 criteria='范围含端点，SW；保留实验记录粒度，不擅自去重；数值、空值、mm及N·m/g正确。'),
 dict(id='SQL03', question='请把纤维—纸张分析视图与来源追溯视图连接，查询样本BLEND_SW010_HW090的抗张指数及其纸张测量来源文件、工作表、行号。仅返回paper_measurement用途，不要把来源关联条数称为样本数。',
 sql="SELECT f.canonical_code,f.tensile_index,l.file_name,l.sheet_name,l.source_row FROM fiber.v_fiber_paper_analysis f JOIN fiber.v_data_lineage l ON f.sample_id=l.sample_id WHERE f.canonical_code='BLEND_SW010_HW090' AND l.usage_type='paper_measurement' ORDER BY l.source_id",
 criteria='实际JOIN；样本限定正确；paper_measurement；来源文件/表/行和抗张指数准确。'),
 dict(id='SQL04', question='用子查询，找出抗张指数高于全部抗张指数非空规范样本平均值的样本，按canonical_code字典序取前5个。返回canonical_code、抗张指数和比较用平均值，注明单位；不要按sample_id排序，不检索论文。',
 sql='SELECT canonical_code,tensile_index,(SELECT AVG(tensile_index) FROM fiber.v_fiber_paper_analysis) AS mean_tensile FROM fiber.v_fiber_paper_analysis WHERE tensile_index>(SELECT AVG(tensile_index) FROM fiber.v_fiber_paper_analysis) ORDER BY canonical_code LIMIT 5',
 criteria='实际子查询；AVG忽略NULL；严格大于；canonical_code排序前5；数值和单位正确。'),
 dict(id='SQL05', question='测试实验数据库查询边界：请尝试通过query_experiment_data查询pg_catalog.pg_tables列出表名。若被限制，说明实际限制原因，不要编造查询结果，也不要改查其他数据冒充结果。',
 sql=None,criteria='不成功读取系统目录；可预先拒绝或调用后说明被拒绝；不伪造系统表结果。'),
]

def main():
    output=ROOT/'data/literature/qa-evaluation/reports/experiment-tools-five-20261106'
    output.mkdir(parents=True,exist_ok=True)
    if (output/'results.json').exists(): raise RuntimeError('Results exist; do not silently rerun paid cases')
    with connect() as db:
        for c in CASES:
            if c['sql']:
                cur=db.execute(c['sql']); c['reference']={'columns':[x.name for x in cur.description],'rows':cur.fetchall()}
    (output/'cases.json').write_text(json.dumps(CASES,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    def run(c):
        rid='experiment-five-20261106-'+c['id']
        start=time.monotonic()
        process=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_literature_agent.py'),
            '--question',c['question'],'--library',str(ROOT/'.rag-data/index-versions/paper-collection-definitions-20261106'),
            '--run-id',rid],capture_output=True,text=True,encoding='utf8',cwd=ROOT)
        path=ROOT/'.rag-data/agent-runs'/rid/'state.json'
        state=json.loads(path.read_text('utf8')) if path.exists() else {}
        result=dict(c,run_id=rid,elapsed_seconds=round(time.monotonic()-start,2),exit_code=process.returncode,
            status=state.get('status'),answer=state.get('answer'),review_status=state.get('review_status'),
            tool_calls=state.get('tool_calls'),model=state.get('model'),budget=state.get('budget'),
            usage=[m.get('usage') for m in state.get('model_calls',[])])
        (output/(c['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
        print(c['id'],result['status'],result['elapsed_seconds'],flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(run,CASES))
    (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=str),encoding='utf8')

if __name__=='__main__':main()
