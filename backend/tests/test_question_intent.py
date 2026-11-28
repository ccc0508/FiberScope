"""Regression cases for the single-agent workflow and its tool dispatch."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from literature_rag.application.question_intent import PUBLISH_TOOL


VIEW = "fiber.v_blend_analysis"
PAPER = "doc_morais"
SQL = "SELECT beating_revolutions FROM fiber.v_blend_analysis"
TABLE_TEXT = "Table 1. X2 Width (μm)"


def action(name, **arguments):
    return dict(name=name, arguments=arguments)


def directory():
    return action("describe_experiment_data", reason="Check real fields", views=[VIEW])


def table():
    return action("read_table", reason="Read the paper table", document_id=PAPER, table_number="1")


def task(id, kind, quote, *, start=None, parent=None, keys=(), clarification=None):
    result = dict(id=id, kind=kind, source_quote=quote, goal=quote)
    if start is not None:
        result["first_action"] = start
    if parent is not None:
        result["depends_on"] = [dict(task_id=parent, outputs=list(keys))]
    if clarification is not None:
        result["clarification"] = clarification
    return result


def decision(*tasks):
    return dict(type="workflow", tasks=list(tasks))


def finish(text, coverage=()):
    return dict(answer=text, coverage=list(coverage))


class NativeCall:
    def __init__(self, index, item):
        self.id = f"native-{index}"
        self.function = SimpleNamespace(name=item["name"], arguments=json.dumps(item["arguments"], ensure_ascii=False))

    def model_dump(self, **_):
        return dict(id=self.id, type="function", function=vars(self.function))


def run(question, *responses, executor=None, budget=None):
    pending = iter(responses)
    prompts = []
    executed = []

    def create(**kwargs):
        prompts.append(dict(kwargs, messages=list(kwargs["messages"])))
        value = next(pending)
        native = [NativeCall(f"{len(prompts)}-{i}", item) for i, item in enumerate(value)] if isinstance(value, list) else None
        content = None if native else value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        message = SimpleNamespace(content=content, tool_calls=native)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls" if native else "stop")],
                               usage=None)

    def execute(request, *_):
        executed.append(request)
        if executor:
            return executor(request)
        if request["tool"] == "describe_experiment_data":
            result = dict(views=[dict(name=VIEW)])
        elif request["tool"] == "query_experiment_data":
            result = dict(ref="[1]", columns=["beating_revolutions"], rows=[[8000]])
        elif request["tool"] == "read_table":
            result = dict(table=dict(ref="[1]", text=TABLE_TEXT))
        elif request["tool"] == "search_literature":
            result = dict(evidence=[dict(ref="[2]", text="8000 revolutions measured in the paper.")])
        else:
            pytest.fail(f"unexpected tool: {request['tool']}")
        return dict(status="completed", result=result)

    adapter = ChatAgentAdapter(SimpleNamespace(
        llm_provider="deepseek", llm_model="deepseek-flash", llm_thinking_enabled=False, llm_reasoning_effort=None,
    ), client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    loop = AgentLoop(adapter, execute, lambda _: None, budget=budget, unified_research=True, first_turn_intent=True,
                     evidence_supplement_enabled=False, paper_directory=[dict(document_id=PAPER, title="Morais")],
                     parallel_search_executor=lambda *_: pytest.fail("unexpected parallel executor"))
    state = loop.run(question, "workflow-test")
    return state, prompts, executed


def test_clock_is_direct_and_first_response_uses_json_mode():
    state, prompts, executed = run("今天星期几？", dict(type="answer", answer="星期六"))
    clock = state["runtime_clock"]
    assert datetime.fromisoformat(clock["iso"]).isoweekday() == clock["iso_weekday"]
    assert clock["timezone"] == "Asia/Shanghai"
    assert clock["iso"] in prompts[0]["messages"][0]["content"]
    assert prompts[0]["response_format"] == {"type": "json_object"}
    assert "tools" not in prompts[0] and not executed and len(prompts) == 1
    assert state["answer"] == "星期六"


def test_public_lookup_is_rejected_during_first_decision():
    question = "首尔今天下午会下雨吗？"
    state, prompts, executed = run(
        question, decision(task("weather", "web", question)), dict(type="answer", answer="目前无法核实实时天气。"),
    )
    assert len(prompts) == 2 and not executed
    assert state["first_decision_recovery"]["status"] == "repaired"
    assert state["answer"] == "目前无法核实实时天气。"
    assert "public_web_searches" not in state


def test_sql_result_unlocks_literature_only_on_next_model_decision():
    sql, literature = "查本地最高样本打浆转数", "按实际转数查论文"
    state, prompts, executed = run(
        f"{sql}；{literature}",
        decision(task("sample", "sql", sql, start=directory()),
                 task("paper", "literature", literature, parent="sample", keys=["beating_revolutions"])),
        [action("query_experiment_data", task_id="sample", reason="Read actual result", sql=SQL),
         action("search_literature", task_id="paper", reason="Too early", query="generic")],
        [action("search_literature", task_id="paper", reason="Use actual value", query="8000 revolutions PFI")],
        finish("库内样本为 8000 转 [1]。论文讨论该档位 [2]。"),
    )
    assert state["status"] == "completed", state
    assert [req["tool"] for req in executed] == [
        "describe_experiment_data", "query_experiment_data", "search_literature",
    ]
    sql_call, early, paper = state["tool_calls"][1:]
    assert sql_call["status"] == "completed" and early["status"] == "blocked"
    assert not any(t["function"]["name"] == "search_literature" for t in prompts[1]["tools"])
    assert '"value": 8000' in str(prompts[2]["messages"])
    assert paper["workflow_inputs"] == {"sample": {
        "beating_revolutions": {"ref": "[1]", "value": 8000, "column": "beating_revolutions", "row_index": 0}
    }}


def test_literature_quote_unlocks_sql_and_rejects_invented_and_same_turn_outputs():
    paper, local = "查表里的宽度单位", "根据实际文献口径查本地"
    state, prompts, executed = run(
        f"{paper}；{local}",
        decision(task("paper", "literature", paper, start=table()),
                 task("local", "sql", local, parent="paper", keys=["width_unit"], start=directory())),
        [action(PUBLISH_TOOL, task_id="paper", output="width_unit", ref="[1]", quote="invented")],
        [action(PUBLISH_TOOL, task_id="paper", output="width_unit", ref="[1]", quote="Width (μm)"),
         action("describe_experiment_data", task_id="local", reason="Too early", views=[VIEW])],
        [action("describe_experiment_data", task_id="local", reason="Match Width (μm)", views=[VIEW])],
        [action("query_experiment_data", task_id="local", reason="Fetch the matched metric", sql=SQL)],
        finish("原表为 μm [1]，已查询本地字段。"),
    )
    assert state["status"] == "completed", state
    assert [req["tool"] for req in executed] == ["read_table", "describe_experiment_data", "query_experiment_data"]
    bad_publish = next(call for call in state["tool_calls"] if call["result"].get("error_code") == "invalid_output_quote")
    assert bad_publish["status"] == "blocked"
    assert "query_experiment_data" not in state["model_calls"][1]["available_tools"]
    assert '"value": "Width (μm)"' in str(prompts[3]["messages"])
    assert [event["status"] for event in state["tool_calls"] if event["request"]["tool"] == "describe_experiment_data"] == [
        "blocked", "blocked", "completed",
    ]
    assert state["tool_calls"][-1]["workflow_inputs"] == {"paper": {"width_unit": {"ref": "[1]", "value": "Width (μm)"}}}


@pytest.mark.parametrize("rows", [[], [[None]]])
def test_empty_or_null_sql_result_never_unlocks_literature(rows):
    sql, paper, date = "查本地打浆转数", "按该转数查论文", "今天星期几"
    def execute(req):
        return dict(status="completed", result=dict(
            views=[],
        ) if req["tool"] == "describe_experiment_data" else dict(
            ref="[1]", columns=["beating_revolutions"], rows=rows,
        ))

    state, _, executed = run(
        f"{date}？{sql}；{paper}",
        decision(task("date", "direct", date), task("sample", "sql", sql, start=directory()),
                 task("paper", "literature", paper, parent="sample", keys=["beating_revolutions"])),
        [action("query_experiment_data", task_id="sample", reason="Fetch value", sql=SQL)],
        finish("今天星期六。未查到可用转数。"),
        finish("今天星期六。未查到可用转数。"),
        executor=execute,
    )
    assert [req["tool"] for req in executed] == ["describe_experiment_data", "query_experiment_data"]
    assert "星期六" in state["answer"] and paper in state["answer"]
    assert state["question_intent"]["tasks"][2]["status"] == "unresolved"


def test_daily_and_research_share_the_normal_final_answer():
    date, paper = "今天星期几", "查本地论文表的宽度单位"
    state, prompts, executed = run(
        f"{date}？{paper}。",
        decision(task("date", "direct", date), task("paper", "literature", paper, start=table())),
        finish("今天星期六。论文中的宽度单位为 μm [1]。"),
    )
    assert len(prompts) == 2 and len(executed) == 1
    assert state["answer"] == "今天星期六。论文中的宽度单位为 μm [1]。"
    assert state["citation_validation"]["status"] == "passed"


def test_clarification_blocks_only_its_dependents():
    stats, threshold, paper = "统计高转数样本", "高转数门槛先问我", "另外查论文表"
    state, _, executed = run(
        f"{stats}，{threshold}；{paper}",
        decision(task("threshold", "clarify", threshold, clarification="门槛是多少转？"),
                 task("stats", "sql", stats, parent="threshold", keys=["threshold"], start=directory()),
                 task("paper", "literature", paper, start=table())),
        finish("表里为 μm [1]。"),
    )
    assert [x["tool"] for x in executed] == ["read_table"]
    assert "门槛是多少转？" in state["answer"] and "μm" in state["answer"]
    assert "query_experiment_data" not in state["model_calls"][-1]["available_tools"]


def test_daily_item_is_answered_when_all_research_waits_for_the_user():
    date, stats, threshold = "今天星期几", "统计高转数样本", "高转数门槛先问我"
    state, _, executed = run(f"{date}？{stats}，{threshold}。",
        decision(task("day", "direct", date),
                 task("threshold", "clarify", threshold, clarification="门槛是多少转？"),
                 task("stats", "sql", stats, parent="threshold", keys=["threshold"])),
        finish("今天星期六。"),
    )
    assert state["status"] == "completed" and not executed
    assert state["answer"].startswith("今天星期六。\n\n请补充")
    assert "门槛是多少转？" in state["answer"]


def test_cycle_is_repaired_once_before_tools_run():
    sql, paper = "查本地数据库", "查论文"
    state, prompts, executed = run(
        f"{sql}；{paper}",
        decision(task("sql", "sql", sql, parent="paper", keys=["source"]),
                 task("paper", "literature", paper, parent="sql", keys=["input"])),
        decision(task("paper", "literature", paper, parent="sql", keys=["input"]),
                 task("sql", "sql", sql, start=directory())),
        [action("query_experiment_data", task_id="sql", reason="Read value", sql=SQL)],
        finish("结果缺少命名字段。"), finish("结果缺少命名字段。"),
    )
    assert state["first_decision_recovery"]["status"] == "repaired"
    assert "circular dependency" in prompts[1]["messages"][-1]["content"]
    assert [req["tool"] for req in executed] == ["describe_experiment_data", "query_experiment_data"]


@pytest.mark.parametrize("via_text", [False, True])
def test_native_and_explicit_actions_use_same_execution_gate(via_text):
    quote = "查试验样本记录"
    query = action("query_experiment_data", task_id="sample", reason="Fetch", sql=SQL)
    response = dict(actions=[query]) if via_text else [query]
    state, _, executed = run(
        quote, decision(task("sample", "sql", quote, start=directory())), response,
        finish("结果在 [1]。示例 JSON 为 " + json.dumps(dict(actions=[query]))),
    )
    assert state["status"] == "completed"
    assert [req["tool"] for req in executed] == ["describe_experiment_data", "query_experiment_data"]


def test_incomplete_action_protocol_is_repaired_without_executing_bare_sql():
    quote = "查试验样本记录"
    state, prompts, executed = run(
        quote, decision(task("sample", "sql", quote, start=directory())), dict(sql=SQL, reason="Fetch"),
        [action("query_experiment_data", task_id="sample", reason="Fetch", sql=SQL)], finish("结果 [1]。"),
    )
    assert state["followup_tool_recoveries"][0]["status"] == "repaired"
    assert "Missing tool name" in prompts[2]["messages"][-1]["content"]
    assert len(executed) == 2


def test_failed_independent_tool_preserves_later_valid_result():
    left, right = "查实验视图", "查论文宽度"
    def execute(req):
        if req["tool"] == "describe_experiment_data":
            raise RuntimeError("private infrastructure details")
        return dict(status="completed", result=dict(table=dict(ref="[1]", text=TABLE_TEXT)))

    state, prompts, executed = run(
        f"{left}；{right}",
        decision(task("sql", "sql", left, start=directory()), task("paper", "literature", right, start=table())),
        finish("论文结果 [1]，实验失败。"), finish("论文结果 [1]，实验失败。"), executor=execute,
    )
    assert [x["tool"] for x in executed] == ["describe_experiment_data", "read_table"]
    assert "tool_execution_failed" in str(prompts[1]["messages"])
    assert "private infrastructure details" not in str(prompts[1]["messages"])
    assert "论文结果" in state["answer"]
