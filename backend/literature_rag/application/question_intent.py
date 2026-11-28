"""Validate and schedule the single agent's local task workflow."""

from collections import defaultdict
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from .evidence_acceptance import EVIDENCE_LOOKUP_TOOLS
from .citation_policy import citation_records


PLAN_TOOL = "declare_question_tasks"
PUBLISH_TOOL = "publish_task_output"
LOCAL_ROLES = frozenset(EVIDENCE_LOOKUP_TOOLS)
TaskID = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
CONFIRM = re.compile(r"先(?:问我|(?:向|和|跟)我确认)|等我(?:确认|提供|指定|回复)|"
                     r"(?:需要|必须)先明确[^，。；！？\n]{0,24}(?:门槛|阈值)|"
                     r"\b(?:ask me first|wait for my (?:confirmation|reply))\b", re.I)
EXPLICIT_PAPER_LOOKUP = re.compile(
    r"(?:(?:去|在|从)(?:本地)?文献库(?:里|中)?\s*(?:检索|查|找|搜)|(?:检索|搜索|查阅)(?:本地)?文献库)"
)
NEGATED_PAPER_LOOKUP = re.compile(r"(?:不必|不用|不需要|不要|禁止|不允许|别)\s*(?:再|去|在|从)?(?:本地)?文献库")


class InitialDecisionFormatError(ValueError):
    def __init__(self, code, raw, usage, finish_reason):
        super().__init__(code)
        self.code, self.raw, self.usage, self.finish_reason = code, raw, usage, finish_reason


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Dependency(StrictModel):
    task_id: TaskID
    outputs: list[TaskID] = Field(min_length=1, max_length=8)


class FirstAction(StrictModel):
    name: str
    arguments: dict


class Task(StrictModel):
    id: TaskID
    source_quote: str = Field(min_length=2, max_length=2000)
    goal: str = Field(min_length=2, max_length=2000)
    depends_on: list[Dependency] = Field(default_factory=list, max_length=12)


class ResearchTask(Task):
    kind: Literal["sql", "literature"]
    paper_quote: str = Field(default="", max_length=200)
    first_action: FirstAction | None = None


class DirectTask(Task):
    kind: Literal["direct"]


class ClarifyTask(Task):
    kind: Literal["clarify"]
    clarification: str = Field(min_length=2, max_length=300)


class Workflow(StrictModel):
    type: Literal["workflow"]
    tasks: list[Annotated[ResearchTask | DirectTask | ClarifyTask, Field(discriminator="kind")]] = Field(
        min_length=1, max_length=16,
    )


class DirectAnswer(StrictModel):
    type: Literal["answer"]
    answer: str = Field(min_length=1)


class PublishOutput(StrictModel):
    task_id: TaskID
    output: TaskID
    ref: str = Field(pattern=r"^\[[1-9][0-9]*\]$")
    quote: str | None = Field(default=None, min_length=1, max_length=2400,
                              description="An exact excerpt from the source text, for literature output.")
    column: str | None = Field(default=None, min_length=1, max_length=200,
                               description="The exact returned column name, for SQL output.")
    row_index: int | None = Field(default=None, ge=0, description="Zero-based result row, for SQL output.")


FIRST_DECISION = TypeAdapter(Annotated[DirectAnswer | Workflow, Field(discriminator="type")])
PUBLISH_SCHEMA = PublishOutput.model_json_schema()
FIRST_DECISION_GUIDANCE = """
Use the runtime Asia/Shanghai clock for date, weekday and time. Public web lookup is unavailable.
Use type=answer for a direct answer, including when current external information cannot be verified.
For local research use type=workflow. Quote exact spans of the user question in source_quote.
Use sql, literature, direct (an independent everyday item in a mixed question), or clarify.
Use clarify with a user-facing question when an essential choice is missing. Link affected tasks
to that clarification. Continue the independent tasks. Do not guess missing conditions.
Use depends_on entries {task_id,outputs} when a task really needs a prerequisite result.
Include EVERY requested step in tasks, including a lookup that will run only later. A phrase like
“先查本地样本实际浆种，再按查到的浆种去文献库找论文” needs two tasks: sql, then literature
depending on the sql task's output (e.g. display_name). If a paper determines the metric to query,
register literature then sql with the paper definition as a required output. Do not stop the plan
at the first lookup or put the downstream lookup into the upstream goal.
Name SQL outputs after SELECT aliases when possible. For literature use meaningful short output keys.
Register later stages without first_action. Add first_action only to research tasks without dependencies,
using an offered local lookup and its exact parameters. Include one first_action per independent ready
research task when its parameters are known. Do not include internal requirement IDs in first_action.
For SQL, first get the view's fields. For a named paper use a verified document ID; use read_table only
with a known table number or chunk ID. Keep result formatting requests for the final answer.
"""


def validate_workflow(workflow, question):
    tasks = {task.id: task for task in workflow.tasks}
    if len(tasks) != len(workflow.tasks):
        raise ValueError("Use a unique id for each task.")
    if not any(task.kind != "direct" for task in tasks.values()):
        raise ValueError("Use type=answer for a wholly direct request.")
    if (EXPLICIT_PAPER_LOOKUP.search(question) and not NEGATED_PAPER_LOOKUP.search(question)
            and not any(task.kind == "literature" for task in tasks.values())):
        raise ValueError("The user explicitly requested a literature lookup. Register that task even if it must wait for SQL.")
    ancestors = {}

    def visit(task_id, seen):
        if task_id in seen:
            raise ValueError(f"Task {task_id} has a circular dependency. Split repeated lookups into ordered tasks.")
        if task_id not in ancestors:
            parents = [item.task_id for item in tasks[task_id].depends_on]
            if (len(set(parents)) != len(parents)
                    or any(parent not in tasks or tasks[parent].kind == "direct" for parent in parents)):
                raise ValueError(f"{task_id}.depends_on must list unique research or clarification task IDs in this plan.")
            ancestors[task_id] = set(parents).union(*(visit(p, seen | {task_id}) for p in parents))
        return ancestors[task_id]

    for task in tasks.values():
        start = question.find(task.source_quote)
        if start < 0 or question.find(task.source_quote, start + 1) >= 0:
            raise ValueError(f"{task.id}.source_quote must be one exact, uniquely occurring span of the user question.")
        visit(task.id, set())
        if task.kind in LOCAL_ROLES:
            end = start + len(task.source_quote)
            tail = re.split(r"[。；;！？!?\n]", question[end:], maxsplit=1)[0]
            if CONFIRM.search(task.source_quote + tail) and not any(
                tasks[ancestor].kind == "clarify" for ancestor in ancestors[task.id]
            ):
                raise ValueError(f"{task.id} requires a clarify prerequisite before any lookup.")


class WorkflowSchedule:
    """Unlock tasks only when their named outputs have verifiable delivered sources."""

    def __init__(self, workflow):
        self.tasks = {task.id: task for task in workflow.tasks}
        self.required = defaultdict(set)
        for task in self.tasks.values():
            for dependency in task.depends_on:
                self.required[dependency.task_id].update(dependency.outputs)
        self.outputs = defaultdict(dict)
        self.evidence = defaultdict(dict)
        self.attempted = set()
        self.directories = set()
        self.requirements = {}

    def missing(self, task):
        return {dep.task_id: sorted(set(dep.outputs) - self.outputs[dep.task_id].keys())
                for dep in task.depends_on if not set(dep.outputs) <= self.outputs[dep.task_id].keys()}

    def ready(self, task):
        return task.kind in LOCAL_ROLES and not self.missing(task)

    def snapshot(self, *, final=False):
        rows = []
        for task in self.tasks.values():
            missing = self.missing(task)
            outputs = self.outputs[task.id]
            row = task.model_dump(exclude={"first_action"}, exclude_none=True)
            if missing:
                status = "unresolved" if final else "waiting"
            elif task.kind == "clarify":
                status = "ask"
            elif task.kind == "direct":
                status = "answer_with_workflow"
            elif self.required[task.id] and self.required[task.id] <= outputs.keys():
                status = "outputs_ready"
            elif final:
                status = "evidence_collected" if self.evidence[task.id] else "unresolved"
            else:
                status = "ready"
            row.update(status=status, missing_inputs=missing,
                       missing_outputs=sorted(self.required[task.id] - outputs.keys()))
            if task.id in self.requirements:
                row["requirement_id"] = self.requirements[task.id]
            if outputs:
                row["outputs"] = outputs.copy()
            rows.append(row)
        return rows

    def record(self, task_id, tool, result):
        if result["status"] != "completed":
            return
        if tool == "describe_experiment_data":
            self.directories.add(task_id)
        if tool == "query_experiment_data" or tool in {"search_literature", "read_table", "read_section", "view_image"}:
            self.attempted.add(task_id)
        for record in citation_records(tool, result):
            self.evidence[task_id][record["ref"]] = (tool, result["result"])
            if tool == "query_experiment_data":
                data = result["result"]
                if len(data.get("rows", [])) == 1 and not data.get("truncated"):
                    for key in self.required[task_id] - self.outputs[task_id].keys():
                        if data.get("columns", []).count(key) == 1:
                            value = data["rows"][0][data["columns"].index(key)]
                            if usable(value):
                                self.outputs[task_id][key] = dict(ref=record["ref"], value=value, column=key, row_index=0)

    def publish(self, raw, earlier_sources):
        try:
            proof = PublishOutput.model_validate(raw)
        except ValidationError as error:
            return failure("invalid_output_selector", validation_message(error))
        if proof.output not in self.required.get(proof.task_id, ()):
            return failure("unknown_output", "Use an outstanding output key from the workflow for this task.")
        if proof.output in self.outputs[proof.task_id]:
            return failure("output_already_published", "Reuse the immutable value already supplied for this output.")
        source = earlier_sources.get(proof.task_id, {}).get(proof.ref)
        if not source:
            return failure("output_source_unavailable", "Use evidence already delivered for this exact task in an earlier turn.")
        tool, data = source
        if tool == "query_experiment_data":
            cols, rows = data.get("columns", []), data.get("rows", [])
            if (proof.quote is not None or cols.count(proof.column) != 1 or proof.row_index is None
                    or proof.row_index >= len(rows) or data.get("truncated")):
                return failure("invalid_output_cell", "Select an exact column and row_index from a complete SQL result.")
            value = rows[proof.row_index][cols.index(proof.column)]
        else:
            entries = {"search_literature": data.get("evidence", []), "read_section": data.get("sources", []),
                       "read_table": [data.get("table", {})]}.get(tool, [])
            value = proof.quote
            if (not value or proof.column is not None or proof.row_index is not None or not any(
                entry.get("ref") == proof.ref and value in entry.get("text", "") for entry in entries
            )):
                return failure("invalid_output_quote", "Copy an exact excerpt supporting this output from the specified paper reference.")
        if not usable(value):
            return failure("empty_output", "The selected value is empty or NULL. Obtain usable evidence before publishing this output.")
        saved = proof.model_dump(exclude={"task_id", "output", "quote"}, exclude_none=True)
        self.outputs[proof.task_id][proof.output] = dict(saved, value=value)
        return dict(status="completed", result=dict(task_id=proof.task_id, output=proof.output, **self.outputs[proof.task_id][proof.output]))


def usable(value):
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value != [] and value != {}


def failure(code, notice):
    return dict(status="blocked", error_code=code, notice=notice, recovery_guidance=notice)


def validation_message(error):
    return " ".join(
        f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in
        error.errors(include_input=False, include_context=False, include_url=False)[:8]
    )
