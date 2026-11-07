"""EXPLAIN without ANALYZE: conservative estimated-work guard, not a timer."""
MAX_TOTAL_COST = 1_000_000
MAX_NODE_ROWS = 1_000_000


class QueryPlanRejected(ValueError):
    def __init__(self, summary):
        super().__init__('查询计划估计工作量超过保护阈值；请在保持原问题口径的前提下减少无关连接、先聚合或增加明确条件。')
        self.summary = summary


def preflight(db, normalized):
    # Only the already allowlisted, regenerated SELECT may enter this function.
    payload=db.execute('EXPLAIN (FORMAT JSON) '+normalized).fetchone()[0]
    root=payload[0]['Plan']
    nodes=[]
    def visit(node):
        nodes.append(node)
        for child in node.get('Plans',[]):visit(child)
    visit(root)
    summary=dict(status='passed',analyze=False,total_cost=float(root.get('Total Cost',0)),
        max_node_rows=max(int(n.get('Plan Rows',0)) for n in nodes),
        node_count=len(nodes),node_types=sorted({n['Node Type'] for n in nodes}),
        limits=dict(total_cost=MAX_TOTAL_COST,max_node_rows=MAX_NODE_ROWS),
        notice='仅优化器估计，不是实际行数或耗时；顺序扫描不单独拒绝，预检不证明统计口径正确。')
    if summary['total_cost']>MAX_TOTAL_COST or summary['max_node_rows']>MAX_NODE_ROWS:
        summary['status']='rejected'
        raise QueryPlanRejected(summary)
    return summary
