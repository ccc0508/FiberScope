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


@pytest.mark.parametrize("mode", ["published_id", "refine_published_id", "unique_current_requirement"])
def test_sql_query_can_follow_directory_while_research_is_still_unlocked(mode):
    quote = "查本地样本的长度"
    rough = dict(role="sql", source_quote=quote, deliverable="按样本代码查长度",
                 metric=dict(population="blends", operation="value", keys=["length"]))
    refined = dict(rough, metric=dict(population="blends", operation="value", keys=["fiber_length_weighted_mm"]))
    directory = ToolCall("directory", "describe_experiment_data", dict(
        reason="Confirm schema", views=["fiber.v_blend_analysis"], requirements=[rough], initial_targets=[1],
    ))
    select = dict(reason="Read confirmed fields", sql="SELECT fiber_length_weighted_mm FROM fiber.v_blend_analysis",
                  requirements=[refined])
    if mode != "unique_current_requirement":
        select["target_requirements"] = ["need_1"]
    if mode == "published_id":
        select.pop("requirements")
    adapter = Fake([
        decision(calls=[declare(task("local", "sql", quote)), directory]),
        decision(calls=[ToolCall("query", "query_experiment_data", select)]),
        decision(json.dumps(dict(answer="长度为 1.119 mm [1]。", coverage=[]), ensure_ascii=False)),
    ])

    def execute(request, *_):
        if request["tool"] == "describe_experiment_data":
            return dict(status="completed", result=dict(views=[]))
        return dict(status="completed", result=dict(ref="[1]", rows=[["1.1190"]]))

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True, first_turn_intent=True,
        evidence_supplement_enabled=False, paper_directory=[],
        parallel_search_executor=lambda *_: pytest.fail("expected sequential SQL calls"),
    ).run(quote, "directory-then-query")
    assert state["status"] == "completed"
    first, second = state["tool_calls"]
    assert first["coverage_schedule"]["target_requirements"] == ["need_1"]
    target = "need_1" if mode == "published_id" else "need_2"
    assert second["status"] == "completed" and second["coverage_schedule"]["target_requirements"] == [target]
    assert "target_requirements" in adapter.requests[1][1]["query_experiment_data"]["properties"]
    if mode == "refine_published_id":
        assert second["coverage_schedule"]["binding_details"]["normalization"] == "bound_to_refined_sql_requirement"


def test_sql_binding_feedback_identifies_bad_position_and_reaches_next_tool_attempt():
    quote = "查本地样本的比例"
    requirement = dict(role="sql", source_quote=quote)
    arguments = dict(reason="Confirm query columns", views=["fiber.v_blend_analysis"], requirements=[requirement])
    adapter = Fake([
        decision(calls=[declare(task("local", "sql", quote)), ToolCall(
            "invalid", "describe_experiment_data", dict(arguments, initial_targets=[2]),
        )]),
        decision(calls=[ToolCall("corrected", "describe_experiment_data", dict(arguments, initial_targets=[1]))]),
        decision(json.dumps(dict(answer="已确认字段。", coverage=[]), ensure_ascii=False)),
    ])
    state = AgentLoop(
        adapter, lambda *_: dict(status="completed", result=dict(views=[])), lambda _: None,
        unified_research=True, first_turn_intent=True, evidence_supplement_enabled=False,
        parallel_search_executor=lambda *_: pytest.fail("expected sequential SQL calls"),
    ).run(quote, "sql-binding-error")
    failed, corrected = state["tool_calls"]
    assert failed["status"] == "blocked" and corrected["status"] == "completed"
    assert failed["result"]["binding_recovery"]["valid_initial_positions"] == [1]
    feedback = failed["result"]["recovery_guidance"]
    assert "initial_targets: [1]" in feedback and quote in feedback
    delivered = next(message for message in adapter.requests[1][0] if message.get("tool_call_id") == "invalid")
    assert json.loads(delivered["content"])["recovery_guidance"] == feedback


def test_sql_cannot_reuse_an_unpublished_id_from_the_same_decision():
    quote = "查本地样本的比例"
    adapter = Fake([
        decision(calls=[declare(task("local", "sql", quote)), ToolCall(
            "directory", "describe_experiment_data", dict(
                reason="Confirm schema", views=["fiber.v_sample_overview"],
                requirements=[dict(role="sql", source_quote=quote)], initial_targets=[1],
            ),
        ), ToolCall("query", "query_experiment_data", dict(
            reason="Read values", sql="SELECT sw_proportion_pct FROM fiber.v_sample_overview",
            target_requirements=["need_1"],
        ))]),
        decision(json.dumps(dict(answer="已确认字段。", coverage=[]), ensure_ascii=False)),
    ])

    def execute(request, *_):
        assert request["tool"] == "describe_experiment_data"
        return dict(status="completed", result=dict(views=[]))

    state = AgentLoop(
        adapter, execute, lambda _: None, unified_research=True, first_turn_intent=True,
        evidence_supplement_enabled=False, parallel_search_executor=lambda *_: pytest.fail("expected sequential SQL calls"),
    ).run(quote, "sql-unpublished-id")
    assert state["tool_calls"][1]["result"]["binding_recovery"]["issue"] == "unavailable_target_requirements"
    assert state["tool_calls"][1]["result"]["binding_recovery"]["available_requirement_ids"] == []


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


def sql_followup_run(second_reply, *later_replies, budget=None):
    quote = "查本地样本的比例"
    directory = dict(name="describe_experiment_data", arguments=dict(
        reason="Confirm fields", views=["fiber.v_blend_analysis"],
        requirements=[dict(role="sql", source_quote=quote)], initial_targets=[1],
    ))
    adapter, prompts = response_adapter(
        dict(plan=dict(tasks=[task("local", "sql", quote)]), actions=[directory], answer=""),
        second_reply, *later_replies,
    )
    requests = []

    def execute(request, *_):
        requests.append(request)
        if request["tool"] == "describe_experiment_data":
            return dict(status="completed", result=dict(views=[]))
        return dict(status="completed", result=dict(ref="[1]", rows=[["50.00"]]))

    state = AgentLoop(
        adapter, execute, lambda _: None, budget,
        unified_research=True, first_turn_intent=True, evidence_supplement_enabled=False,
        parallel_search_executor=lambda *_: pytest.fail("expected sequential SQL calls"),
        public_search=lambda *_: pytest.fail("unexpected public search"),
    ).run(quote, "sql-followup-format")
    return state, prompts, requests


@pytest.mark.parametrize("named", [False, True])
def test_recovers_both_followup_tool_payloads_without_model_retry(named):
    arguments = dict(sql="SELECT sw_proportion_pct FROM fiber.v_blend_analysis",
                     reason="Read proportion", target_requirements=["need_1"])
    reply = dict(name="query_experiment_data", arguments=arguments) if named else arguments
    state, prompts, calls = sql_followup_run(reply, dict(answer="比例为 50% [1]。", coverage=[]))
    assert state["answer"] == "比例为 50% [1]。"
    assert [m["stage"] for m in state["model_calls"]] == ["decide", "decide", "decide"]
    assert state["model_calls"][1]["calls"] == []
    assert "Function Calling" in prompts[1]["messages"][0]["content"]
    assert calls[-1]["sql"] == arguments["sql"]
    event = state["tool_calls"][-1]
    assert event["coverage_schedule"]["target_requirements"] == ["need_1"]
    assert event["model_delivery"]["messages"][0]["role"] == "user"
    assert state["followup_tool_recoveries"] == [
        dict(model_call=2, issue=None, status="normalized", tool="query_experiment_data", call_id="text-lookup-2"),
    ]


def test_ambiguous_sql_payload_receives_eligible_ids_and_one_tool_repair():
    args = dict(sql="SELECT sw_proportion_pct FROM fiber.v_blend_analysis", reason="Read proportion")
    repaired = dict(name="query_experiment_data", arguments=dict(args, target_requirements=["need_1"]))
    state, prompts, calls = sql_followup_run(
        dict(args, target_requirements=["unknown"]), repaired, dict(answer="比例为 50% [1]。", coverage=[]),
    )
    assert [m["stage"] for m in state["model_calls"]] == [
        "decide", "decide", "followup_tool_format_repair", "decide",
    ]
    feedback = json.loads(state["model_calls"][2]["input_messages"][-1]["content"])
    assert feedback["pending_sql_targets"] == ["need_1"]
    assert "target_requirements" in feedback["problem"]
    assert {tool["function"]["name"] for tool in prompts[2]["tools"]} == {
        "describe_experiment_data", "query_experiment_data",
    }
    assert len(calls) == 2 and state["followup_tool_recoveries"][0]["status"] == "repaired"
    assert state["tool_calls"][-1]["coverage_schedule"]["target_requirements"] == ["need_1"]


def test_failed_followup_repair_closes_with_gap_without_repeated_execution():
    bad = dict(sql="SELECT sw_proportion_pct FROM fiber.v_blend_analysis", reason="Missing task ID")
    state, prompts, calls = sql_followup_run(bad, bad, dict(answer="还缺少实际查询结果。", coverage=[]))
    assert [m["stage"] for m in state["model_calls"]] == [
        "decide", "decide", "followup_tool_format_repair", "finalize",
    ]
    assert state["followup_tool_recoveries"][0]["status"] == "repair_failed"
    assert state["stop_reason"] == "followup_tool_format_unresolved"
    assert len(calls) == 1 and "tools" not in prompts[-1]


def test_followup_tool_repair_preserves_closing_budget():
    bad = dict(sql="SELECT sw_proportion_pct FROM fiber.v_blend_analysis", reason="Missing task ID")
    state, _, calls = sql_followup_run(
        bad, dict(answer="还缺少实际查询结果。", coverage=[]), budget=AgentBudget(max_model_calls=4),
    )
    assert [m["stage"] for m in state["model_calls"]] == ["decide", "decide", "finalize"]
    assert state["followup_tool_recoveries"][0]["status"] == "repair_unavailable"
    assert len(calls) == 1


def test_sql_in_terminal_answer_remains_an_example():
    example = dict(name="query_experiment_data", arguments=dict(
        sql="SELECT sw_proportion_pct FROM fiber.v_blend_analysis", reason="Example", target_requirements=["need_1"],
    ))
    text = "示例查询\n```json\n" + json.dumps(example) + "\n```"
    state, _, calls = sql_followup_run(dict(answer=text, coverage=[]))
    assert state["answer"] == text and len(calls) == 1
    assert "followup_tool_recoveries" not in state


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


def test_correction_of_web_task_field_keeps_local_lookup_and_denies_new_web_authorization():
    local = "请查论文A的纤维宽度"
    public = "另外联网查首尔天气"
    question = f"{local}；{public}"
    tasks = [task("paper", "literature", local), task("web", "web", public)]
    wrong = [tasks[0], dict(tasks[1], clarification="是否另外联网？")]
    adapter, prompts = response_adapter(
        dict(plan=dict(tasks=wrong), actions=[], answer=""),
        dict(plan=dict(tasks=tasks), actions=[first_search(local)], answer=""),
        dict(answer="已从本地证据核对 [1]。", coverage=[]),
    )
    state = run(adapter, question, execute=lambda *_: dict(
        status="completed", result=dict(evidence=[dict(ref="[1]", text="Local evidence.")]),
    ), public=lambda *_: pytest.fail("invalid original plan granted web access"))
    assert state["status"] == "completed" and state["first_decision_recovery"]["status"] == "repaired"
    feedback = json.loads(prompts[1]["messages"][-1]["content"])
    assert feedback["issues"][0]["field"].endswith(".clarification")
    assert "kind=clarify" in feedback["issues"][0]["problem"]
    assert state["tool_calls"][0]["provider_call_id"] == "repaired-initial-1"
    assert state["question_intent"]["tasks"][1]["status"] == "web_scope_unconfirmed"


def test_ready_literature_is_added_in_one_correction_and_waiting_sql_is_omitted():
    paper = "另查论文A的纤维宽度"
    threshold = "门槛先问我"
    count = "统计高转数样本"
    question = f"{count}，{threshold}；{paper}"
    plan = dict(tasks=[
        task("threshold", "clarify", threshold, clarification="门槛是多少？"),
        task("count", "sql", count, depends_on=["threshold"]),
        task("paper", "literature", paper),
    ])
    adapter, prompts = response_adapter(
        dict(plan=plan, actions=[], answer=""),
        dict(plan=plan, actions=[first_search(paper)], answer=""),
        dict(answer="已确认宽度 [1]。", coverage=[]),
    )
    state = run(adapter, question, execute=lambda request, *_: dict(
        status="completed", result=dict(evidence=[dict(ref="[1]", text="Local evidence.")]),
    ))
    assert state["status"] == "completed"
    assert state["first_decision_recovery"]["initial_error"] == "missing_ready_local_actions"
    ready = json.loads(prompts[1]["messages"][-1]["content"])["issues"][0]["ready_tasks"]
    assert [t["id"] for t in ready] == ["paper"]
    assert "query_experiment_data" not in state["model_calls"][1]["available_tools"]
    assert [t["request"]["tool"] for t in state["tool_calls"]] == ["search_literature"]
    assert "门槛是多少？" in state["answer"]


def test_unoffered_name_and_invalid_table_selector_are_reported_before_binding():
    quote = "查论文A的变量表"
    adapter = Fake([
        decision(calls=[declare(task("paper", "literature", quote)), ToolCall("missing-table", "read_table", dict(
            document_id="paper", reason="find", requirements=[dict(role="literature", source_quote=quote)],
        ))]),
        decision(calls=[ToolCall("bad-name", "read_literature_table", dict(
            document_id="paper", table_number="1", reason="find",
        ))]),
        decision(calls=[ToolCall("table", "read_table", dict(
            document_id="paper", table_number="1", reason="find",
            requirements=[dict(role="literature", source_quote=quote)], initial_targets=[1],
        ))]),
        decision(json.dumps(dict(answer="表 1 [1]。", coverage=[]), ensure_ascii=False)),
    ])
    executed = []

    def execute(request, *_):
        executed.append(request)
        return dict(status="completed", result=dict(table=dict(ref="[1]", text="Width (μm)")))

    state = run(adapter, quote, execute=execute)
    assert [request["tool"] for request in executed] == ["read_table"]
    bad_params, bad_name, _ = state["tool_calls"]
    assert bad_name["result"]["error_code"] == "tool_not_allowed"
    assert "read_table" in bad_name["result"]["available_tools"]
    assert bad_params["result"]["error_code"] == "invalid_arguments"
    assert "search_literature" in bad_params["result"]["recovery_guidance"]


def test_tool_exception_preserves_other_results_and_is_delivered_as_observation():
    quote = "查询论文A"
    requirement = dict(role="literature", source_quote=quote)
    adapter = Fake([
        decision(calls=[ToolCall("bad", "read_table", dict(
            document_id="paper", table_number="1", reason="find",
            requirements=[requirement], initial_targets=[1],
        )), ToolCall("ok", "search_literature", dict(
            query="results", reason="find related text",
            requirements=[requirement], initial_targets=[1],
        ))]),
        decision(json.dumps(dict(answer="根据正文 [1]。", coverage=[]), ensure_ascii=False)),
    ])

    def execute(request, *_):
        if request["tool"] == "read_table":
            raise RuntimeError("private infrastructure detail")
        return dict(status="completed", result=dict(evidence=[dict(ref="[1]", text="Local evidence")]))

    state = run(adapter, quote, execute=execute)
    assert state["status"] == "completed"
    failed, successful = state["tool_calls"]
    assert successful["status"] == "completed"
    assert failed["result"]["worker_diagnostic"]["exceptions"][0]["type"] == "RuntimeError"
    observation = json.loads(next(message["content"] for message in adapter.requests[1][0]
                                  if message.get("tool_call_id") == "bad"))
    assert observation["error_code"] == "tool_execution_failed"
    assert "Continue independent tasks" in observation["recovery_guidance"]
    assert "worker_diagnostic" not in observation and "private infrastructure detail" not in str(observation)
