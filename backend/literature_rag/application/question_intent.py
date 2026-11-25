"""Validate the first decision's scopes before any external lookup."""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


PLAN_TOOL = "declare_question_tasks"
MAX_WEB_SEARCHES = 2
LOCAL_ROLES = frozenset({"literature", "sql"})
CROSS_SCOPE_DEPENDENCY = "cross-scope-dependency"
PUBLIC_PREFIX = re.compile(
    r"^(?:(?:然后|另外|顺便|also\b|and\b)\s*)?(?:请\s*)?(?:(?:联网|上网|(?:在)?网上)(?:查询?|搜索|搜)|"
    r"search (?:the )?web(?: for)?|look up online)\s*[:：]?\s*", re.I,
)
PUBLIC_CLAUSE_START = re.compile(
    r"(?:^|[\n，,。；;：:！？?!])\s*(?:(?:然后|另外|顺便|also\b|and\b)\s*)?(?:请\s*)?$", re.I,
)
CONFIRM_WITH_USER = re.compile(
    r"先(?:问我|(?:向|和|跟)我确认)|等我(?:确认|提供|指定|回复)|"
    r"(?:需要|必须)先明确(?P<parameter>[^，。；！？\n]{1,24}?(?:门槛|阈值))|"
    r"\b(?:ask me first|wait for my (?:confirmation|reply))\b", re.I,
)
OFFLINE_REQUEST = re.compile(
    r"(?:不(?:要|得|用|许|使用|允许)?|禁止|无需|勿)\s*(?:联网|上网|网上|网络搜索|(?:搜索|访问)互联网)|"
    r"\b(?:do not|don't|never|no)\s+(?:use\s+(?:the\s+)?)?(?:web|internet|online|search the web)\b", re.I,
)
PRIVATE_SCOPE = re.compile(
    r"(?:本地|内部|未公开|我们的|我(?:的)?(?:实验|数据|样本|论文)|数据库|文献库|科研|论文|实验数据|"
    r"纸浆|纤维素|植物纤维|打浆|抗张|粗度|造纸|上述|前面|刚才|该(?:值|结果|样本|试验)|"
    r"\b(?:fiberscope|postgres(?:ql)?|paper|research|thesis|pulp|papermaking|cellulose|tensile|dataset|private|internal)\b|"
    r"\b(?:api[_ -]?key|password|secret|bearer)\b|"
    r"(?:doc|need|txt|blend|sample)[_-][\w-]+|https?://|[/\\@=`\[\]])", re.I,
)


class TaskScope(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,23}$")
    kind: Literal["direct", "web", "literature", "sql", "clarify"]
    source_quote: str = Field(min_length=2, max_length=2000)
    depends_on: list[str] = Field(default_factory=list, max_length=10)
    clarification: str | None = Field(default=None, min_length=2, max_length=300)


class QuestionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskScope] = Field(min_length=1, max_length=16)


PLAN_SCHEMA = QuestionPlan.model_json_schema()
FIRST_DECISION_GUIDANCE = """
Classify intent and choose the first ready tools in this same decision.
For a single direct task, return its answer now. For a clear research request, its existing local
tool calls and requirements already declare intent. Never use web for research, papers or experiment data.
For web, clarification, or mixed direct/research tasks, include a task plan in this decision.
Include separate verbatim user clauses (source_quote); exclude shared formatting instructions.
Only a clarification and its dependent task may quote overlapping text.
Use literature for local papers, sql for local measurements, direct for general knowledge or date/time,
web for day-to-day public facts needing a current lookup, clarify for a necessary missing choice.
Give the clarify task a short user-facing question. Use clarify instead of a lookup for a clause
that lacks an essential user choice, such as a requested threshold with no value. Never invent a
choice or derive a substitute from database statistics. Link separate clauses requiring that choice
using depends_on.
Tasks needing clarification or depending on it must wait. Dispatch independent ready local lookups
now, with existing requirements whose source_quote lies within a matching ready
literature or sql task. If both local and public information are requested, the user must explicitly ask
for a web lookup in the public clause. Copy that clause as written, including the user's web instruction.
The runtime fixes and searches only the public query from that clause. Never generate or revise a web query
using other tasks or local results. In mixed requests leave direct items for final composition.
If a date/time is needed, use the runtime clock below. Never search for the current weekday in that timezone.
If a current public fact needs a lookup and web search is unavailable, still register it as web. Do not guess.
"""


def _public_query(question, task, mixed):
    clause = task.source_quote
    prefix = PUBLIC_PREFIX.match(clause)
    if OFFLINE_REQUEST.search(unicodedata.normalize("NFKC", question)):
        return None
    position = question.index(clause)
    if prefix and position and not PUBLIC_CLAUSE_START.search(question[:position]):
        return None
    if not prefix and (mixed or question.strip(" \t\n。！？?!") != clause.strip(" \t\n。！？?!")):
        return None
    query = clause[prefix.end():].strip(" \t。！？?!") if prefix else clause.strip(" \t。！？?!")
    normalized = unicodedata.normalize("NFKC", query)
    if (not 2 <= len(query) <= 160 or PRIVATE_SCOPE.search(normalized)
            or any(c in normalized for c in "\r\n,;，；。!?")
            or any(unicodedata.category(c).startswith("C") for c in normalized)):
        return None
    return query


def validate_plan(arguments, question):
    plan = QuestionPlan.model_validate(arguments)
    tasks = {task.id: task for task in plan.tasks}
    if len(tasks) != len(plan.tasks) or sum(task.kind == "web" for task in plan.tasks) > MAX_WEB_SEARCHES:
        raise ValueError("invalid_task_count")
    ranges = {}
    for task in plan.tasks:
        start = question.find(task.source_quote)
        if start < 0 or question.find(task.source_quote, start + 1) >= 0:
            raise ValueError("source_quote_must_be_unique_and_verbatim")
        ranges[task.id] = (start, start + len(task.source_quote))
        if bool(task.clarification) != (task.kind == "clarify") or set(task.depends_on) - tasks.keys():
            raise ValueError("invalid_clarification_or_dependency")

    pending_by_task = {}

    def blockers(task_id, visiting):
        if task_id in visiting:
            raise ValueError("cyclic_dependencies")
        if task_id in pending_by_task:
            return pending_by_task[task_id]
        task = tasks[task_id]
        parents = [tasks[parent] for parent in task.depends_on]
        pending = set().union(*(blockers(parent.id, visiting | {task_id}) for parent in parents))
        if task.kind == "clarify":
            pending.add(task_id)
        elif any((parent.kind == "web") != (task.kind == "web") for parent in parents
                 if parent.kind != "clarify"):
            # Separate evidence scopes cannot feed one another.
            pending.add(CROSS_SCOPE_DEPENDENCY)
        pending_by_task[task_id] = pending
        return pending

    for index, task in enumerate(plan.tasks):
        start, end = ranges[task.id]
        for other in plan.tasks[:index]:
            left, right = ranges[other.id]
            if start >= right or left >= end:
                continue
            # A clarification may reuse its dependent clause. Public and
            # executable local scopes must always have separate source text.
            if not (task.kind == "clarify" and task.id in blockers(other.id, set())
                    or other.kind == "clarify" and other.id in blockers(task.id, set())):
                raise ValueError("overlapping_task_scopes")

    # Preserve an explicit request to settle a missing choice before doing the
    # lookup, even when the model labels that clause as a ready SQL task.
    for task in plan.tasks:
        if task.kind not in LOCAL_ROLES:
            continue
        if blockers(task.id, set()) & tasks.keys():
            continue
        _, end = ranges[task.id]
        before_next_clause = re.split(r"[。；;！？!?\n]", question[end:], maxsplit=1)[0]
        confirmation = CONFIRM_WITH_USER.search(task.source_quote + before_next_clause)
        if confirmation:
            parameter = confirmation.group("parameter")
            tasks[task.id] = task.model_copy(update={
                "kind": "clarify",
                "clarification": f"请明确{parameter}。" if parameter else "请补充这项查询所需的条件。",
            })
            pending_by_task.clear()
    resolved = []
    for task in tasks.values():
        pending = blockers(task.id, set())
        result = task.model_dump(exclude_none=True)
        result.update(status="waiting" if pending else "ready", blocked_by=sorted(pending))
        if task.kind == "clarify" and pending == {task.id}:
            result["status"] = "ask"
        if task.kind == "web" and not pending:
            query = _public_query(question, task, len(tasks) > 1)
            if query is None:
                result["status"] = "web_scope_unconfirmed"
            else:
                result["query"] = query
        resolved.append(result)
    return resolved


def rejection_code(error):
    return "invalid_task_declaration" if isinstance(error, ValidationError) else str(error)
