"""Build the API fixtures in tests/fixtures/api/ from the API models.

Run `uv run python tests/api_fixtures.py` after changing a model or a fixture here. `test_api_contract.py` fails
when the saved files differ from what this module builds.

The goblin-bribe results for decision-1@foundry and clef-flash@workers-ai are real responses to the plan's request.
Everything else is made up to be consistent: the same suite, cases, targets, and runs appear across files.
"""

import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fakes import FakeProvider, Responder
from jevtester.normalize import (
    TargetResult,
    choice_confidence,
)
from jevtester.preflight import target_warnings
from jevtester.providers import DecisionProvider, Health, RawResult, target_result
from jevtester.runner.jobs import cache_key
from jevtester.schemas import (
    ApiError,
    ApiErrorBody,
    DecideBody,
    ErrorDetail,
    PolicyDetail,
    PolicyList,
    PolicySummary,
    PolicyThreshold,
    ProbeCell,
    ProbeReport,
    ProbeSummary,
    ProbeVariant,
    QuestionSetBody,
    RunCounts,
    RunCreate,
    RunCreated,
    RunEvent,
    RunSummary,
    SweepPoint,
    SweepResult,
    TargetCounts,
)
from jevtester.service import Service
from jevtester.spec import (
    Case,
    ChoiceQuestion,
    DecisionRequest,
    Expectation,
    QuestionSet,
    load_config,
)
from jevtester.store.files import SuiteFiles
from jevtester.store.runs import RunStore

ROOT = Path(__file__).parent.parent
OUT = ROOT / "tests" / "fixtures" / "api"
SYSTEMONE = ROOT / "tests" / "fixtures" / "systemone"

T0 = datetime(2026, 10, 24, 14, 0, 0, tzinfo=UTC)

FOUNDRY = "decision-1@foundry"
WORKERS = "clef-flash@workers-ai"
OLLAMA = "clef-flash@ollama"
RUN_TARGETS = [FOUNDRY, WORKERS, OLLAMA]
BASELINE_RUN = "0001"
RUN = "0002"
"""The run the run fixtures show. Its baseline is run 0001."""
OLLAMA_REASON = "clef-flash isn't pulled"

CONFIG = load_config(ROOT / "jevtester.toml")


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


# Questions and cases

PLAN_REQUEST = load_json(SYSTEMONE / "parley_request.json")
FOUNDRY_RESPONSE = load_json(SYSTEMONE / "parley_response_foundry.json")
WORKERS_RESPONSE = load_json(SYSTEMONE / "parley_response_workers_ai.json")
"""A real Clef-flash response to the plan's request, from 2026-10-24, in its Cloudflare envelope."""

# The fixtures ask the plan's questions, whatever suites/question-sets/parley.yaml has become, so the real
# responses in tests/fixtures/systemone/ still answer them. The cases come from suites/parley.yaml.
QUESTIONS = DecisionRequest.model_validate(
    {"state": PLAN_REQUEST["state"], "questions": PLAN_REQUEST["questions"]}
).questions
QUESTION_SET = QuestionSet(name="parley", questions=QUESTIONS)
CASES = SuiteFiles(ROOT / "suites").load_suite("parley").cases

_intent = QUESTIONS["intent"]
assert isinstance(_intent, ChoiceQuestion)
OLD_INTENT = ChoiceQuestion(
    instructions=_intent.instructions, criteria={k: v for k, v in _intent.criteria.items() if k != "wait"}
)
OLD_QUESTION_SET = QuestionSet(name="parley", questions={**QUESTIONS, "intent": OLD_INTENT})

DRAFT_CASE = Case(
    id="hobgoblin-gold",
    state={
        "party": "Three adventurers, one holding a coin purse",
        "monsters": "Six hobgoblins guarding a bridge",
        "player_says": "Here is gold for safe passage.",
    },
    expected={"intent": Expectation(answer="parley"), "bribe": Expectation(answer=True)},
    expected_action="parley_succeeds",
    tags=["bribe"],
    provenance="claude-draft",
)
CASE_BY_ID = {case.id: case for case in CASES}

# Answers for each case and target, as (intent probabilities, bribe probability, reaction probabilities).
type AnswerPlan = tuple[dict[str, float], float, list[float]]
PLANS: dict[str, dict[str, AnswerPlan]] = {
    FOUNDRY: {
        "orc-charge": (
            {"parley": 0.004, "evade": 0.002, "fight": 0.991, "wait": 0.003},
            0.012,
            [0.702, 0.241, 0.041, 0.011, 0.005],
        ),
        "kobold-retreat": (
            {"parley": 0.021, "evade": 0.903, "fight": 0.004, "wait": 0.072},
            0.008,
            [0.112, 0.468, 0.301, 0.092, 0.027],
        ),
        "gnoll-watch": (
            {"parley": 0.011, "evade": 0.094, "fight": 0.003, "wait": 0.892},
            0.004,
            [0.061, 0.252, 0.493, 0.151, 0.043],
        ),
    },
    WORKERS: {
        "orc-charge": (
            {"parley": 0.0103, "evade": 0.0051, "fight": 0.9764, "wait": 0.0082},
            0.0207,
            [0.6511, 0.2702, 0.0538, 0.0172, 0.0077],
        ),
        "kobold-retreat": (
            {"parley": 0.0408, "evade": 0.3913, "fight": 0.0094, "wait": 0.5585},
            0.0151,
            [0.1307, 0.4412, 0.3108, 0.0905, 0.0268],
        ),
        "gnoll-watch": (
            {"parley": 0.0204, "evade": 0.1302, "fight": 0.0051, "wait": 0.8443},
            0.0083,
            [0.0702, 0.2611, 0.4704, 0.1508, 0.0475],
        ),
    },
}
LATENCY = {FOUNDRY: [1550.0, 1412.0, 1604.0, 1488.0], WORKERS: [2470.0, 2310.0, 2544.0, 2391.0]}
INPUT_TOKENS = [185, 178, 181, 183]


def score_of(probabilities: list[float]) -> float:
    return sum(level * p for level, p in enumerate(probabilities))


def plan_body(plan: AnswerPlan, digits: int | None) -> dict[str, Any]:
    """A System One response body for one case, rounded the way Workers AI rounds."""

    def r(value: float) -> float:
        return round(value, digits) if digits is not None else value

    intent, bribe, reaction = plan
    return {
        "model": "clef-flash" if digits is not None else "microsoft-decision-1",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": max(intent, key=intent.__getitem__),
                "confidence": r(choice_confidence(intent)),
                "probabilities": {k: r(v) for k, v in intent.items()},
            },
            "bribe": {"type": "noul", "noul": r(bribe)},
            "reaction": {
                "type": "score",
                "score": r(score_of(reaction)),
                "confidence": r(0.31),
                "legend": {str(i): text for i, text in enumerate(QUESTION_SET_LEVELS)},
                "probabilities": {str(i): r(p) for i, p in enumerate(reaction)},
            },
        },
    }


_reaction = QUESTIONS["reaction"]
QUESTION_SET_LEVELS: list[str] = list(getattr(_reaction, "criteria", []))


def make_raw(target: str, case: Case) -> RawResult:
    index = CASES.index(case)
    request = DecisionRequest(state=case.state, questions=QUESTIONS)
    sent = request.system_one_body(CONFIG.targets[target].model)
    if target == FOUNDRY and case.id == "goblin-bribe":
        body = FOUNDRY_RESPONSE
        response_body: Any = body
    elif target == WORKERS and case.id == "goblin-bribe":
        body = WORKERS_RESPONSE["result"]
        response_body = WORKERS_RESPONSE
    else:
        body = plan_body(PLANS[target][case.id], 4 if target == WORKERS else None)
        output = 0 if target == WORKERS else 3
        body["usage"] = {"input_tokens": INPUT_TOKENS[index], "output_tokens": output}
        response_body = {"result": body, "success": True, "errors": [], "messages": []} if target == WORKERS else body
    return RawResult(
        request_body=sent,
        status=200,
        response_body=response_body,
        system_one=body,
        latency_ms=LATENCY[target][index],
    )


def make_result(target: str, case: Case) -> TargetResult:
    """A result as the service builds it, with the target's warnings first."""
    request = DecisionRequest(state=case.state, questions=QUESTIONS)
    config_target = CONFIG.targets[target]
    result = target_result(target, request, make_raw(target, case), config_target.capabilities)
    result.warnings = [*target_warnings(config_target), *result.warnings]
    return result


# The baseline ran the older question set, which has no "wait" option, so some intent answers differ.
BASELINE_INTENT = {
    (FOUNDRY, "gnoll-watch"): "evade",
    (WORKERS, "kobold-retreat"): "evade",
    (WORKERS, "gnoll-watch"): "evade",
}


def old_raw(target: str, case: Case) -> RawResult:
    """A response to the older question set: intent without "wait", renormalized."""
    raw = make_raw(target, case)
    assert raw.system_one is not None
    body = json.loads(json.dumps(raw.system_one))
    intent = body["answers"]["intent"]
    probabilities = {k: v for k, v in intent["probabilities"].items() if k != "wait"}
    total = sum(probabilities.values())
    probabilities = {k: v / total for k, v in probabilities.items()}
    choice = BASELINE_INTENT.get((target, case.id), max(probabilities, key=probabilities.__getitem__))
    if choice != max(probabilities, key=probabilities.__getitem__):
        # Move most of the probability to the baseline's answer.
        probabilities = {k: (0.7 if k == choice else 0.3 / (len(probabilities) - 1)) for k in probabilities}
    intent.update(choice=choice, probabilities=probabilities, confidence=choice_confidence(probabilities))
    request = DecisionRequest(state=case.state, questions=OLD_QUESTION_SET.questions)
    sent = request.system_one_body(CONFIG.targets[target].model)
    envelope: Any = {"result": body, "success": True, "errors": [], "messages": []} if target == WORKERS else body
    return raw.model_copy(update={"request_body": sent, "response_body": envelope, "system_one": body})


def respond_for(target: str) -> Responder:
    def respond(request: DecisionRequest, body: dict[str, Any]) -> RawResult:
        case = next(case for case in CASES if case.state == request.state)
        intent = request.questions.get("intent")
        if isinstance(intent, ChoiceQuestion) and "wait" not in intent.criteria:
            return old_raw(target, case)
        return make_raw(target, case)

    return respond


HEALTH = {
    FOUNDRY: Health(credential="Azure CLI, refreshes in 41 min"),
    OLLAMA: Health(reason=OLLAMA_REASON, detail="Run ollama pull clef-flash (11-12 GB)"),
}
WORKERS_HEALTH = Health(credential="Wrangler sign-in, refreshes in 52 min")
MLX_HEALTH = Health(reason="The MLX server isn't running", detail="The model download isn't finished")


def providers() -> dict[str, DecisionProvider]:
    fakes: dict[str, DecisionProvider] = {}
    for target in CONFIG.targets.values():
        health = WORKERS_HEALTH if target.provider == "workers-ai" else HEALTH.get(target.name, MLX_HEALTH)
        respond = respond_for(target.name) if target.name in PLANS else None
        fakes[target.name] = FakeProvider(target, respond, health)
    return fakes


# The runs use a config without Foundry's request rate, so a fixture run doesn't wait between requests. The targets
# fixtures use the real config.
RUN_CONFIG = CONFIG.model_copy(
    update={
        "targets": {
            name: target.model_copy(
                update={"capabilities": target.capabilities.model_copy(update={"requests_per_minute": None})}
            )
            for name, target in CONFIG.targets.items()
        }
    }
)


def fixture_service(root: Path) -> Service:
    """A service over a copy of `suites/` in `root`, with fake providers that answer from the fixtures.

    The copy's suite has a Claude draft, the store has both question set versions, and the cache holds two Workers AI
    results, so run 0002 shows every kind of job.
    """
    shutil.copytree(ROOT / "suites", root / "suites", dirs_exist_ok=True)
    files = SuiteFiles(root / "suites")
    files.save_question_set(QUESTION_SET)
    suite = files.load_suite("parley")
    files.save_suite(suite.model_copy(update={"cases": [*suite.cases, DRAFT_CASE]}))
    store = RunStore(Path(":memory:"))
    store.record_version(OLD_QUESTION_SET, at(-40))
    store.record_version(QUESTION_SET, at(5))
    for target_name, case_id in CACHED:
        case = CASE_BY_ID[case_id]
        request = DecisionRequest(state=case.state, questions=QUESTIONS)
        store.cache_put(cache_key(CONFIG.targets[target_name], request, 0), RESULTS[target_name, case_id], at(-30))
    return Service(CONFIG, providers(), files=files, store=store, clock=lambda: at(10))


def run_service(root: Path) -> Service:
    """A fixture service whose runs use the run config."""
    service = fixture_service(root)
    service.config = RUN_CONFIG
    return service


async def populate(service: Service) -> str:
    """Run the baseline 0001 on the older question set and run 0002 on the current one, for real, then store the probe
    run 0003 and the cancelled run 0004.

    Returns:
        Run 0002's event stream, as the API sends it.
    """
    old = RunCreate(suite="parley", targets=[FOUNDRY, WORKERS], question_set_version=OLD_QUESTION_SET.version)
    baseline = await start_and_wait(service, old)
    created = await service.start_run(RunCreate(suite="parley", targets=RUN_TARGETS, baseline=baseline.id))
    events = [event async for event in service.run_events(created.id)]
    await service.wait_run(created.id)
    service.store.save_run(PROBE_RUN)
    service.store.save_run(CANCELLED_RUN)
    return "".join(sse_event(index, event) for index, event in enumerate(events))


def prepared_service(root: Path) -> tuple[Service, str]:
    """A fixture service after `populate`, and run 0002's event stream."""
    service = run_service(root)
    return service, asyncio.run(populate(service))


async def start_and_wait(service: Service, body: RunCreate) -> RunCreated:
    created = await service.start_run(body)
    await service.wait_run(created.id)
    return created


def service_fixtures(root: Path) -> dict[str, BaseModel | str]:
    """The fixtures for the live routes, made by the service itself."""
    fresh = fixture_service(root / "fresh")
    unchecked = fresh.list_targets()
    checked = asyncio.run(fresh.check_targets())
    goblin = CASES[0]
    single = DecideBody(state=goblin.state, questions=QUESTIONS, targets=[FOUNDRY])
    partial = DecideBody(state=goblin.state, questions=QUESTIONS, targets=[FOUNDRY, WORKERS, OLLAMA])
    fixtures: dict[str, BaseModel | str] = {
        "get_targets.json": checked,
        "get_targets.unchecked.json": unchecked,
        "post_targets_check.json": checked,
        "post_decide.json": asyncio.run(fresh.decide(single)),
        "post_decide.partial.json": asyncio.run(fresh.decide(partial)),
    }
    service, events = prepared_service(root / "prepared")
    old, new = OLD_QUESTION_SET.version[:12], QUESTION_SET.version[:12]
    fixtures |= {
        "get_suites.json": service.list_suites(),
        "get_suites_{name}.json": service.get_suite("parley"),
        "get_question-sets.json": service.list_question_sets(),
        "get_question-sets_{name}.json": service.get_question_set("parley"),
        "get_question-sets_{name}_versions.json": service.question_set_versions("parley"),
        "get_question-sets_{name}_versions_{version}.json": service.question_set_version("parley", old),
        "get_question-sets_{name}_diff.json": service.diff_question_set("parley", old, new),
        "get_runs.json": service.list_runs(),
        "get_runs_{id}.json": service.get_run(RUN),
        "get_runs_{id}_events.sse": events,
        "post_runs_{id}_cancel.json": asyncio.run(service.cancel_run("0004")),
        "get_suites_{name}_check.json": service.check_suite("parley"),
        "get_runs_{id}_metrics.json": service.run_metrics(RUN),
        "get_runs_{id}_confusion.json": service.run_confusion(RUN, "intent", WORKERS),
        "get_runs_{id}_calibration.json": service.run_calibration(RUN, "intent", WORKERS, 10),
        "get_runs_{id}_changes.json": service.run_changes(RUN, BASELINE_RUN),
        "get_runs_{id}_compare.json": service.compare_runs(RUN, BASELINE_RUN),
        "get_runs_{id}_cases_{case_id}.json": service.run_case(RUN, "goblin-bribe"),
        "get_runs_{id}_report.json": service.run_report(RUN),
    }
    # The fixtures for the routes that change things come last, so they don't show in the others.
    new_case = Case(
        id="bugbear-toll",
        state={
            "party": "Three adventurers at a rope bridge",
            "monsters": "Two bugbears demanding a toll",
            "player_says": "Fine. Ten silver each, and we cross.",
        },
        expected={"intent": Expectation(answer="parley"), "bribe": Expectation(answer=True)},
        tags=["bribe"],
    )
    fixtures |= {
        "put_question-sets_{name}.json": service.save_question_set("parley", QuestionSetBody(questions=QUESTIONS)),
        "post_suites_{name}_cases.json": service.add_case("parley", new_case),
        "post_runs.json": asyncio.run(start_and_wait(service, RunCreate(suite="parley"))),
    }
    return fixtures


def slim(result: TargetResult) -> TargetResult:
    return result.model_copy(update={"request_body": None, "raw": None})


RESULTS: dict[tuple[str, str], TargetResult] = {
    (target, case.id): make_result(target, case) for target in (FOUNDRY, WORKERS) for case in CASES
}
CACHED = {(WORKERS, "goblin-bribe"), (WORKERS, "orc-charge")}


def counts(done: dict[str, dict[str, int]], jobs_per_target: int, targets: list[str]) -> RunCounts:
    rows: list[TargetCounts] = []
    for target in targets:
        row = done.get(target, {})
        rows.append(
            TargetCounts(
                target=target,
                jobs=jobs_per_target,
                sent=row.get("sent", 0),
                cached=row.get("cached", 0),
                failed=row.get("failed", 0),
                skipped=row.get("skipped", 0),
                skip_reason=OLLAMA_REASON if target == OLLAMA and row.get("skipped") else None,
            )
        )
    sent = sum(r.sent for r in rows)
    cached = sum(r.cached for r in rows)
    failed = sum(r.failed for r in rows)
    skipped = sum(r.skipped for r in rows)
    return RunCounts(
        jobs=jobs_per_target * len(targets),
        done=sent + cached + failed + skipped,
        sent=sent,
        cached=cached,
        failed=failed,
        skipped=skipped,
        targets=rows,
    )


FINAL_COUNTS = counts(
    {FOUNDRY: {"sent": 4}, WORKERS: {"sent": 2, "cached": 2}, OLLAMA: {"skipped": 4}}, len(CASES), RUN_TARGETS
)
RUN_COST = sum(
    result.cost_usd or 0.0 for key, result in RESULTS.items() if key not in CACHED and result.cost_usd is not None
)


def run_summary(run_id: str, **changes: Any) -> RunSummary:
    summary = RunSummary(
        id=RUN,
        kind="suite",
        suite="parley",
        question_set="parley",
        question_set_version=QUESTION_SET.version,
        policy=None,
        policy_version=None,
        targets=RUN_TARGETS,
        repeats=1,
        variants=[],
        no_cache=False,
        baseline=BASELINE_RUN,
        status="finished",
        case_count=len(CASES),
        counts=FINAL_COUNTS,
        cost_usd=RUN_COST,
        created_at=at(10),
        started_at=at(10),
        finished_at=at(10.2),
    )
    return summary.model_copy(update={"id": run_id, **changes})


POLICY_VERSION = "6c1f0a9e5b7d4c3a2f1e0d9c8b7a6f5e4d3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a"

PROBE_VARIANTS: list[ProbeVariant] = ["option_order", "key_order"]
PROBE_INSTANCES: dict[ProbeVariant, int] = {"option_order": 3, "key_order": 1}
PROBE_JOBS_PER_TARGET = len(CASES) * (1 + sum(PROBE_INSTANCES.values()))
PROBE_RUN = run_summary(
    "0003",
    kind="probe",
    variants=PROBE_VARIANTS,
    targets=[FOUNDRY, WORKERS],
    baseline=None,
    status="running",
    counts=counts(
        {FOUNDRY: {"sent": 14}, WORKERS: {"sent": 9, "cached": 4}}, PROBE_JOBS_PER_TARGET, [FOUNDRY, WORKERS]
    ),
    cost_usd=0.0000634,
    created_at=at(20),
    started_at=at(20),
    finished_at=None,
)
CANCELLED_RUN = run_summary(
    "0004",
    baseline=None,
    status="cancelled",
    counts=counts({FOUNDRY: {"sent": 2}, WORKERS: {"cached": 2}, OLLAMA: {"skipped": 4}}, len(CASES), RUN_TARGETS),
    cost_usd=None,
    created_at=at(30),
    started_at=at(30),
    finished_at=at(30.1),
)


def sse_event(index: int, event: RunEvent) -> str:
    return f"event: {event.type}\nid: {index}\ndata: {event.model_dump_json()}\n\n"


# Metrics


def probe_report() -> ProbeReport:
    changed = {
        (WORKERS, "kobold-retreat", "option_order"): 2,
        (WORKERS, "gnoll-watch", "option_order"): 1,
        (FOUNDRY, "kobold-retreat", "option_order"): 1,
    }
    cells: list[ProbeCell] = []
    for target in (FOUNDRY, WORKERS):
        for case in CASES:
            for variant in PROBE_VARIANTS:
                instances = PROBE_INSTANCES[variant]
                count = changed.get((target, case.id, variant), 0)
                cells.append(
                    ProbeCell(
                        case_id=case.id,
                        target=target,
                        variant=variant,
                        instances=instances,
                        changed=count,
                        change_rate=count / instances,
                    )
                )
    summary: list[ProbeSummary] = []
    for target in (FOUNDRY, WORKERS):
        for variant in PROBE_VARIANTS:
            group = [c for c in cells if c.target == target and c.variant == variant]
            rate = sum(c.changed for c in group) / sum(c.instances for c in group)
            summary.append(ProbeSummary(target=target, variant=variant, cases=len(group), change_rate=rate))
    return ProbeReport(run_id="0003", variants=PROBE_VARIANTS, cells=cells, summary=summary)


# Question sets


# Policies

POLICY_YAML = """\
# Turns the parley questions into a referee action. The policy format arrives in build step 7.
name: parley
bands:
  intent: {act: 0.8, confirm: 0.5}
composites:
  goodwill:
    bribe: 0.6
    reaction: 0.4
rules:
  - when: intent == "fight"
    action: battle
  - when: intent == "evade"
    action: evade
  - when: intent == "wait"
    action: wait
  - when: intent == "parley" and goodwill >= goodwill_threshold
    action: parley_succeeds
  - when: intent == "parley"
    action: parley_fails
thresholds:
  goodwill_threshold: 0.6
  per_target:
    clef-flash@workers-ai: {goodwill_threshold: 0.55}
costs:
  parley_succeeds: {parley_fails: 5, escalate: 1}
"""
POLICY = PolicyDetail(
    name="parley",
    version=POLICY_VERSION,
    yaml=POLICY_YAML,
    actions=["battle", "evade", "wait", "parley_succeeds", "parley_fails", "escalate"],
    thresholds=[
        PolicyThreshold(name="intent.act", value=0.8, per_target={}),
        PolicyThreshold(name="intent.confirm", value=0.5, per_target={}),
        PolicyThreshold(name="goodwill_threshold", value=0.6, per_target={WORKERS: 0.55}),
    ],
    suites=["parley"],
)


def sweep() -> SweepResult:
    points: list[SweepPoint] = []
    for step in range(11):
        value = step / 10
        decided = max(0.0, 1.0 - value * 0.6)
        points.append(
            SweepPoint(
                value=value,
                decided_share=round(decided, 4),
                error_rate=round(max(0.0, 0.3 - value * 0.3), 4),
                cost=round(max(0.0, 6.0 - value * 5.0), 4),
            )
        )
    return SweepResult(
        policy="parley", run_id=RUN, target=FOUNDRY, threshold="goodwill_threshold", current=0.6, points=points
    )


def error(code: Any, message: str, field: str | None = None, details: list[ErrorDetail] | None = None) -> ApiError:
    return ApiError(error=ApiErrorBody(code=code, message=message, field=field, details=details or []))


def build(root: Path) -> dict[str, BaseModel | str]:
    """Every fixture, keyed by file name.

    Args:
        root: An empty directory for the fixture services' copies of `suites/`.
    """
    live = service_fixtures(root)
    return {
        **live,
        "post_decide.422.json": error(
            "invalid_request",
            "Unknown target: clef@nowhere",
            "targets.0",
            [ErrorDetail(field="targets.0", message="Unknown target: clef@nowhere")],
        ),
        "get_suites_{name}.404.json": error("not_found", "No suite named reaction"),
        "post_suites_{name}_cases.409.json": error(
            "conflict",
            "The suite already has a case goblin-bribe",
            "id",
            [ErrorDetail(field="id", message="The suite already has a case goblin-bribe")],
        ),
        "put_question-sets_{name}.422.json": error(
            "invalid_request",
            "List should have at least 2 items after validation, not 1",
            "questions.reaction.score.criteria",
            [
                ErrorDetail(
                    field="questions.reaction.score.criteria",
                    message="List should have at least 2 items after validation, not 1",
                )
            ],
        ),
        "get_runs_{id}.404.json": error("not_found", "No run 0999"),
        "get_runs_{id}_probes.json": probe_report(),
        "post_probes.json": RunCreated(id="0003"),
        "get_policies.json": PolicyList(
            policies=[PolicySummary(name="parley", version=POLICY_VERSION, actions=POLICY.actions, suites=["parley"])]
        ),
        "get_policies_{name}.json": POLICY,
        "put_policies_{name}.json": POLICY,
        "put_policies_{name}.422.json": error(
            "invalid_request",
            "rules.3.action: unknown action parley_succeds",
            "rules.3.action",
            [
                ErrorDetail(field="rules.3.action", message="Unknown action parley_succeds"),
                ErrorDetail(field="thresholds.goodwill_threshold", message="Input should be a valid number"),
            ],
        ),
        "post_policies_{name}_sweep.json": sweep(),
    }


def render(fixture: BaseModel | str) -> str:
    if isinstance(fixture, str):
        return fixture
    return json.dumps(fixture.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def write(out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*"):
        if stale.suffix in {".json", ".sse"}:
            stale.unlink()
    with tempfile.TemporaryDirectory() as root:
        fixtures = build(Path(root))
    for name, fixture in fixtures.items():
        (out / name).write_text(render(fixture))


if __name__ == "__main__":
    write()
