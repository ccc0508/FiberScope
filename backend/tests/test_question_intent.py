import json
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from literature_rag.adapters.providers.agent_chat import ChatAgentAdapter, ToolCall, decode_initial_decision
from literature_rag.adapters.providers.public_web import BRAVE_SEARCH_URL, BravePublicSearch
from literature_rag.application.agent_loop import AgentBudget, AgentLoop
from literature_rag.application.question_intent import InitialDecisionFormatError, PLAN_TOOL, validate_plan
from literature_rag.application.tools import SCHEMAS
from tests.test_agent_loop import Fake, decision


def task(id, kind, source_quote, **options):
    return dict(id=id, kind=kind, source_quote=source_quote, **options)


def declare(*tasks):
    return ToolCall("plan", PLAN_TOOL, dict(tasks=list(tasks)))


def run(adapter, question, *, execute=lambda *_: pytest.fail("unexpected local call"), public=None):
    return AgentLoop(
        adapter, execute, lambda _: None, unified_research=True, first_turn_intent=True,
        evidence_supplement_enabled=False, paper_directory=[], public_search=public,
    ).run(question, "intent")


def test_direct_uses_current_clock_and_no_additional_call():
    adapter = Fake([decision("今天是星期三。")])
    result = run(adapter, "今天星期几？")
    assert result["answer"] == "今天是星期三。"
    assert len(adapter.requests) == 1
    messages, schemas, _ = adapter.requests[0]
    clock = result["runtime_clock"]
    assert clock["timezone"] == "Asia/Shanghai"
    assert clock["iso"].endswith("+08:00") and clock["iso"] in messages[0]["content"]
    assert datetime.fromisoformat(clock["iso"]).isoweekday() == clock["iso_weekday"]
    assert PLAN_TOOL in schemas and "query_experiment_data" in schemas


def test_default_research_executes_first_lookup_without_a_routing_turn():
    search = ToolCall("search", "search_literature", dict(
        query="fibre morphology", reason="find evidence",
        requirements=[dict(role="literature", source_quote="论文报告的结果")], initial_targets=[1],
    ))
    adapter = Fake([decision(calls=[search]), decision(json.dumps(
        {"answer": "论文报告了该结果 [1]。", "coverage": []}, ensure_ascii=False,
    ))])
    lookups = []

    def execute(request, *_):
        lookups.append((len(adapter.requests), request["tool"]))
        return dict(status="completed", result=dict(evidence=[dict(ref="[1]", text="Evidence.")]))

    state = run(adapter, "查询论文报告的结果", execute=execute, public=lambda *_: pytest.fail("outbound query"))
    assert state["status"] == "completed"
    assert lookups == [(1, "search_literature")]
    assert state["question_intent"]["kind"] == "research"
    assert len(adapter.requests) == 2 and PLAN_TOOL not in adapter.requests[1][1]


def test_mixed_web_clarification_and_independent_local_lookup_use_separate_contexts():
    question = "查论文A的结果；确认实验转数；查询该转数下的样本；再计算这些样本的均值；另外联网查首尔今天天气"
    plan = declare(
        task("paper", "literature", "查论文A的结果"),
        task("speed", "clarify", "确认实验转数", clarification="你指的是哪个打浆转数？"),
        task("samples", "sql", "查询该转数下的样本", depends_on=["speed"]),
        task("mean", "sql", "再计算这些样本的均值", depends_on=["samples"]),
        task("weather", "web", "联网查首尔今天天气"),
    )
    paper = ToolCall("paper", "search_literature", dict(
        query="paper A result", reason="find result",
        requirements=[dict(role="literature", source_quote="论文A的结果")], initial_targets=[1],
    ))
    blocked = ToolCall("try_blocked", "describe_experiment_data", dict(
        views=["fiber.v_sample_overview"], reason="samples",
        requirements=[dict(role="sql", source_quote="查询该转数下的样本")], initial_targets=[1],
    ))
    repeat = ToolCall("forged", PLAN_TOOL, dict(tasks=[
        task("swap", "web", "查论文A的结果", correction_id="quote_1"),
    ]))
    adapter = Fake([
        decision(calls=[plan, paper, blocked]),
        decision(calls=[repeat]),
        decision(json.dumps({"answer": "论文A报告了结果 [1]。", "coverage": []}, ensure_ascii=False)),
        decision("首尔今天天气信息来自网页来源 1。"),
    ])
    web_queries = []

    def public(query, _):
        web_queries.append(query)
        return [dict(title="Weather", url="https://example.com", snippet="UNTRUSTED_WEB_SNIPPET")]

    def execute(request, *_):
        assert request["tool"] == "search_literature"
        assert len(adapter.requests) == 1
        return dict(status="completed", result=dict(evidence=[dict(ref="[1]", text="LOCAL_ONLY_MARKER")]))

    state = run(adapter, question, execute=execute, public=public)
    assert state["status"] == "completed"
    assert PLAN_TOOL not in adapter.requests[1][1]
    assert web_queries == ["首尔今天天气"]
    assert "你指的是哪个打浆转数" in state["answer"]
    assert "论文A报告了结果 [1]" in state["answer"] and "网页来源 1" in state["answer"]
    assert state["tool_calls"][1]["result"]["error_code"] == "lookup_outside_ready_task_scope"
    assert state["public_web_sources"] == [dict(title="Weather", url="https://example.com", index=1)]
    assert state["question_intent"]["tasks"][3]["blocked_by"] == ["speed"]
    assert {r["role"] for r in state["task_contract"]["requirements"]} == {"literature"}
    assert all("UNTRUSTED_WEB_SNIPPET" not in str(request) for request in adapter.requests[:-1])
    web_context, web_tools, _ = adapter.requests[-1]
    assert web_tools == {} and "LOCAL_ONLY_MARKER" not in str(web_context) and "论文A" not in str(web_context)
    assert "UNTRUSTED_WEB_SNIPPET" in str(web_context)


def test_premature_acknowledgment_does_not_replace_ready_research():
    task_quote = "查询论文A的结果"
    adapter = Fake([
        decision("我会先登记。", calls=[declare(task("paper", "literature", task_quote))]),
        decision(calls=[ToolCall("search", "search_literature", dict(
            query="paper A result", reason="find result",
            requirements=[dict(role="literature", source_quote=task_quote)], initial_targets=[1],
        ))]),
        decision(json.dumps({"answer": "论文给出了实验结果 [1]。", "coverage": []}, ensure_ascii=False)),
    ])
    state = run(adapter, task_quote, execute=lambda *_: dict(
        status="completed", result=dict(evidence=[dict(ref="[1]", text="Actual result")]),
    ))
    assert state["status"] == "completed"
    assert state["answer"] == "论文给出了实验结果 [1]。"


def test_explicit_guard_on_missing_threshold_prevents_sql_dispatch():
    sql_quote = "统计针叶木高转数的样本数，需要先明确高转数的门槛"
    plan = declare(task("samples", "sql", sql_quote))
    sql = ToolCall("sql", "query_experiment_data", dict(
        sql="SELECT count(*) FROM fiber.v_sample_overview",
        reason="count samples",
    ))
    adapter = Fake([decision(calls=[plan, sql])])
    state = run(adapter, sql_quote)
    assert state["status"] == "completed"
    assert state["review_status"] == "not_required"
    assert len(adapter.requests) == 1 and not state["tool_calls"]
    assert "请明确高转数的门槛" in state["answer"]


def test_clarification_can_share_text_with_its_blocked_lookup():
    quote = "统计针叶木高转数的样本数"
    question = quote + "，需要先明确高转数的门槛"
    plan = declare(
        task("threshold", "clarify", question, clarification="请给出具体转数。"),
        task("count", "sql", quote, depends_on=["threshold"]),
    )
    clarify, count = validate_plan(plan.arguments, question)
    assert clarify["status"] == "ask"
    assert count["status"] == "waiting" and count["blocked_by"] == ["threshold"]


@pytest.mark.parametrize(("question", "scope"), [
    ("不要联网查首尔今天天气", "联网查首尔今天天气"),
    ("联网查本地BLEND_SW050的抗张指数", "联网查本地BLEND_SW050的抗张指数"),
    ("查论文结果；首尔今天天气", "首尔今天天气"),
    ("查实验结果；联网查上述样本的抗张指数", "联网查上述样本的抗张指数"),
    ("联网查首尔今天天气；不使用网络搜索", "联网查首尔今天天气"),
])
def test_unsafe_or_unconfirmed_public_scope_has_no_query(question, scope):
    item, = validate_plan(dict(tasks=[task("public", "web", scope)]), question)
    assert item["status"] == "web_scope_unconfirmed" and "query" not in item


def test_dependency_cycle_rejected_and_no_outbound_call():
    adapter = Fake([decision(calls=[declare(
        task("first", "web", "联网查首尔天气", depends_on=["second"]),
        task("second", "web", "联网查北京天气", depends_on=["first"]),
    )])])
    state = run(adapter, "联网查首尔天气；联网查北京天气", public=lambda *_: pytest.fail("outbound query"))
    assert state["question_intent"] == dict(status="rejected", error_code="cyclic_dependencies")
    assert "请分别说明" in state["answer"]


def test_missing_web_key_produces_explicit_availability_message():
    question = "首尔今天天气怎么样？"
    adapter = Fake([decision(calls=[declare(task("weather", "web", question))])])
    state = run(adapter, question)
    assert state["status"] == "completed" and "暂未配置" in state["answer"]
    assert len(adapter.requests) == 1 and state["tool_attempts"] == 0


def test_provider_receives_only_the_locked_query_and_returns_safe_links():
    def send(request):
        assert str(request.url) == BRAVE_SEARCH_URL and request.method == "POST"
        assert request.headers["X-Subscription-Token"] == "example-key"
        body = json.loads(request.content)
        assert body["q"] == "首尔今天天气" and body["spellcheck"] is False
        return httpx.Response(200, json={"web": {"results": [
            {"title": "<strong>天气预报</strong>", "description": "晴", "url": "https://weather.example/"},
            {"title": "Unsafe", "description": "Unsafe", "url": "javascript:alert(1)"},
        ]}})

    with httpx.Client(transport=httpx.MockTransport(send)) as client:
        result = BravePublicSearch("example-key", client)("首尔今天天气", 5)
    assert result == [dict(title="天气预报", snippet="晴", url="https://weather.example/")]


def test_chat_adapter_dispatches_initial_json_actions_without_fabricating_native_ids():
    quote = "查询论文A的结果"
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs["response_format"] == {"type": "json_object"}
            assert "tools" not in kwargs
            content = dict(plan=None, answer="", actions=[dict(name="search_literature", arguments=dict(
                query="paper A result", reason="find result",
                requirements=[dict(role="literature", source_quote=quote)], initial_targets=[1],
            ))])
        else:
            assert "response_format" not in kwargs
            assert all(message["role"] != "tool" for message in kwargs["messages"])
            assert "Example evidence" in str(kwargs["messages"])
            content = dict(answer="论文有明确的实验结果 [1]。", coverage=[])
        message = SimpleNamespace(content=json.dumps(content, ensure_ascii=False), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    adapter = ChatAgentAdapter(
        SimpleNamespace(llm_provider="deepseek", llm_model="deepseek-flash", llm_thinking_enabled=False,
                        llm_reasoning_effort=None),
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
    )
    state = run(adapter, quote, execute=lambda *_: dict(
        status="completed", result=dict(evidence=[dict(ref="[1]", text="Example evidence")]),
    ))
    assert state["status"] == "completed"
    assert state["answer"] == "论文有明确的实验结果 [1]。"
    assert len(calls) == 2
    assert "First decision JSON protocol" in state["model_calls"][0]["input_messages"][0]["content"]


def response_adapter(*outputs):
    prompts = []
    replies = iter(outputs)

    def create(**request):
        prompts.append(request)
        content = next(replies)
        if isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        message = SimpleNamespace(content=content, tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    settings = SimpleNamespace(llm_provider="deepseek", llm_model="deepseek-flash", llm_thinking_enabled=False,
                               llm_reasoning_effort=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return ChatAgentAdapter(settings, client=client), prompts


def first_search(quote):
    return dict(name="search_literature", arguments=dict(
        query="paper A result", reason="find result",
        requirements=[dict(role="literature", source_quote=quote)], initial_targets=[1],
    ))


def test_missing_empty_answer_and_flat_tool_arguments_recover_without_model_retry():
    quote = "查询论文A的实验结果"
    search = first_search(quote)
    adapter, prompts = response_adapter(
        dict(plan=None, actions=[dict(name=search["name"], **search["arguments"])]),
        dict(answer="论文报告了结果 [1]。", coverage=[]),
    )

    def execute(request, *_):
        assert len(prompts) == 1
        assert request["query"] == "paper A result"
        return dict(status="completed", result=dict(evidence=[dict(ref="[1]", text="Evidence.")]))

    state = run(adapter, quote, execute=execute)
    assert state["status"] == "completed"
    assert "first_decision_recovery" not in state
    assert state["model_calls"][0]["format_normalizations"] == ["default_empty_answer", "wrapped_lookup_arguments:1"]
    assert "coverage as an array" not in prompts[0]["messages"][0]["content"]
    assert "coverage as an array" in prompts[1]["messages"][0]["content"]


@pytest.mark.parametrize("raw", [
    '{"plan":null,"actions":[],"answer":"","plan":null}',
    '{"plan":null,"actions":[{"name":"search_literature","query":"changed","arguments":{"query":"old"}}],"answer":""}',
])
def test_conflicting_or_duplicate_fields_require_repair(raw):
    with pytest.raises(InitialDecisionFormatError):
        decode_initial_decision(raw, SCHEMAS, None, "stop")


def test_invalid_json_gets_one_format_retry_before_local_lookup():
    quote = "查询论文A的实验结果"
    broken = '{"plan":null,"actions":['
    adapter, prompts = response_adapter(
        broken,
        dict(plan=None, actions=[first_search(quote)], answer=""),
        dict(answer="论文报告了结果 [1]。", coverage=[]),
    )

    def execute(request, *_):
        assert len(prompts) == 2
        return dict(status="completed", result=dict(evidence=[dict(ref="[1]", text="Evidence.")]))

    state = run(adapter, quote, execute=execute)
    assert state["status"] == "completed"
    assert [call["stage"] for call in state["model_calls"]] == ["decide", "initial_format_repair", "decide"]
    assert state["model_calls"][0]["raw_message"] == broken
    assert state["first_decision_recovery"] == dict(status="repaired", initial_error="invalid_json")
    assert prompts[1]["response_format"] == {"type": "json_object"}
    assert json.loads(prompts[1]["messages"][-1]["content"])["previous_output_excerpt"] == broken


def test_second_format_error_ends_run_and_keeps_both_raw_responses():
    adapter, prompts = response_adapter("{bad", "{still bad")
    state = run(adapter, "今天星期几？")
    assert len(prompts) == 2 and state["tool_calls"] == []
    assert state["status"] == "failed" and state["stop_reason"] == "initial_decision_format_failed"
    assert state["first_decision_recovery"] == dict(status="failed", initial_error="invalid_json",
                                                  repair_error="invalid_json")
    assert [call["raw_message"] for call in state["model_calls"]] == ["{bad", "{still bad"]


def test_repair_does_not_consume_reserved_closing_calls():
    adapter, prompts = response_adapter("{bad")
    state = AgentLoop(
        adapter, lambda *_: pytest.fail("unexpected local call"), lambda _: None,
        AgentBudget(max_model_calls=3), unified_research=True, first_turn_intent=True,
        evidence_supplement_enabled=False,
    ).run("今天星期几？", "no-repair-budget")
    assert len(prompts) == 1
    assert state["stop_reason"] == "initial_decision_format_failed"
    assert state["first_decision_recovery"]["status"] == "skipped_budget"


def test_new_web_task_in_repair_cannot_execute_without_first_authorization():
    question = "首尔今天会下雨吗？"
    repaired = dict(plan=dict(tasks=[task("weather", "web", question)]), actions=[], answer="")
    adapter, prompts = response_adapter("{bad", repaired)
    state = run(adapter, question, public=lambda *_: pytest.fail("web query authorized by repair"))
    assert len(prompts) == 2 and state["status"] == "completed"
    assert state["question_intent"]["tasks"][0]["status"] == "web_scope_unconfirmed"
    assert state["public_web_searches"] == []


def test_repair_preserves_validation_of_original_web_scope():
    question = "首尔今天会下雨吗？"
    plan = dict(tasks=[task("weather", "web", question)])
    adapter, prompts = response_adapter(
        dict(plan=plan, actions=[], answer="", coverage=[]),
        dict(plan=plan, actions=[], answer=""),
        "公开预报显示有雨，见网页来源 1。",
    )
    queries = []

    def public(query, _):
        queries.append(query)
        return [dict(title="Weather", url="https://example.com", snippet="Rain today")]

    state = run(adapter, question, public=public)
    assert queries == ["首尔今天会下雨吗"] and len(prompts) == 3
    assert state["status"] == "completed" and state["first_decision_recovery"]["status"] == "repaired"


def test_repair_cannot_change_initial_valid_task_dependencies():
    question = "统计高转数样本；先问我门槛"
    locked = dict(tasks=[
        task("count", "sql", "统计高转数样本", depends_on=["threshold"]),
        task("threshold", "clarify", "先问我门槛", clarification="请指定门槛。"),
    ])
    changed = dict(tasks=[task("count", "sql", "统计高转数样本")])
    adapter, prompts = response_adapter(
        dict(plan=locked, actions=[], answer="", coverage=[]),
        dict(plan=changed, actions=[], answer=""),
    )
    state = run(adapter, question)
    assert len(prompts) == 2 and state["status"] == "failed"
    assert state["first_decision_recovery"]["repair_error"] == "changed_locked_task_plan"
