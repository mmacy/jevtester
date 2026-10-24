"""Build the API fixtures in tests/fixtures/api/ from the API models.

Run `uv run python tests/api_fixtures.py` after changing a model or a fixture here. `test_api_contract.py` fails
when the saved files differ from what this module builds.

The goblin-bribe results for decision-1@foundry and clef-flash@workers-ai are real responses to the plan's request.
Everything else is made up to be consistent: the same suite, cases, targets, and runs appear across files.
"""

import asyncio
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from fakes import FakeProvider, Responder
from jevtester.normalize import (
    Answer,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    TargetResult,
    choice_confidence,
)
from jevtester.preflight import target_warnings
from jevtester.providers import DecisionProvider, Health, RawResult, target_result
from jevtester.schemas import (
    AnswerChange,
    ApiError,
    ApiErrorBody,
    Calibration,
    CalibrationBin,
    CaseCreated,
    CaseResult,
    ChangeSummary,
    ConfusionMatrix,
    DecideBody,
    DecisionMetrics,
    ErrorDetail,
    FinishedEvent,
    OptionDiff,
    PolicyDetail,
    PolicyList,
    PolicySummary,
    PolicyThreshold,
    ProbeCell,
    ProbeReport,
    ProbeSummary,
    ProbeVariant,
    ProgressEvent,
    QuestionDiff,
    QuestionMetrics,
    QuestionSetDetail,
    QuestionSetDiff,
    QuestionSetList,
    QuestionSetSummary,
    QuestionSetVersion,
    QuestionSetVersions,
    ResultEvent,
    RunCase,
    RunChanges,
    RunCounts,
    RunCreated,
    RunEvent,
    RunList,
    RunMetrics,
    RunReport,
    RunSummary,
    SuiteCheck,
    SuiteDetail,
    SuiteList,
    SuiteSummary,
    SweepPoint,
    SweepResult,
    TargetCounts,
    TargetMetrics,
    TargetSkippedEvent,
    WordingCheck,
)
from jevtester.service import Service
from jevtester.spec import (
    Case,
    ChoiceQuestion,
    DecisionRequest,
    Expectation,
    Question,
    QuestionSet,
    Suite,
    load_config,
)

ROOT = Path(__file__).parent.parent
OUT = ROOT / "tests" / "fixtures" / "api"
SYSTEMONE = ROOT / "tests" / "fixtures" / "systemone"

T0 = datetime(2026, 10, 24, 14, 0, 0, tzinfo=UTC)

FOUNDRY = "decision-1@foundry"
WORKERS = "clef-flash@workers-ai"
OLLAMA = "clef-flash@ollama"
RUN_TARGETS = [FOUNDRY, WORKERS, OLLAMA]
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

QUESTIONS = DecisionRequest.model_validate(
    {"state": PLAN_REQUEST["state"], "questions": PLAN_REQUEST["questions"]}
).questions
QUESTION_SET = QuestionSet(name="parley", questions=QUESTIONS)

_intent = QUESTIONS["intent"]
assert isinstance(_intent, ChoiceQuestion)
OLD_INTENT = ChoiceQuestion(
    instructions=_intent.instructions, criteria={k: v for k, v in _intent.criteria.items() if k != "wait"}
)
OLD_QUESTION_SET = QuestionSet(name="parley", questions={**QUESTIONS, "intent": OLD_INTENT})

CASES = [
    Case(
        id="goblin-bribe",
        state=PLAN_REQUEST["state"],
        expected={
            "intent": Expectation(answer="parley"),
            "bribe": Expectation(answer=True),
            "reaction": Expectation(answer=3, tolerance=1),
        },
        expected_action="parley_succeeds",
        tags=["bribe"],
    ),
    Case(
        id="orc-charge",
        state={
            "party": "Four adventurers in a narrow corridor",
            "monsters": "Five orcs, shields up, 30 feet away",
            "player_says": "Charge them! Swords out!",
        },
        expected={
            "intent": Expectation(answer="fight"),
            "bribe": Expectation(answer=False),
            "reaction": Expectation(answer=0, tolerance=1),
        },
        expected_action="battle",
        tags=["combat"],
    ),
    Case(
        id="kobold-retreat",
        state={
            "party": "Two adventurers, one wounded",
            "monsters": "Eight kobolds with spears, 60 feet away",
            "player_says": "Back away slowly toward the door we came in by.",
        },
        expected={
            "intent": Expectation(answer="evade"),
            "bribe": Expectation(answer=False),
            "reaction": Expectation(answer=1, tolerance=1),
        },
        expected_action="evade",
        tags=["evade"],
    ),
    Case(
        id="gnoll-watch",
        state={
            "party": "Three adventurers behind a pillar",
            "monsters": "Four gnolls arguing over a carcass, 50 feet away",
            "player_says": "We stay still and watch what they do.",
        },
        expected={
            "intent": Expectation(answer="wait"),
            "bribe": Expectation(answer=False),
            "reaction": Expectation(answer=2, tolerance=1),
        },
        expected_action="wait",
        tags=["wait"],
    ),
]
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
SUITE = Suite(
    name="parley", question_set="parley", cases=[*CASES, DRAFT_CASE], policy="parley", targets=[FOUNDRY, WORKERS]
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


def respond_for(target: str) -> Responder:
    def respond(request: DecisionRequest, body: dict[str, Any]) -> RawResult:
        case = next(case for case in CASES if case.state == request.state)
        return make_raw(target, case)

    return respond


HEALTH = {
    FOUNDRY: Health(credential="Azure CLI, refreshes in 41 min"),
    OLLAMA: Health(reason=OLLAMA_REASON, detail="Run ollama pull clef-flash (11-12 GB)"),
}
WORKERS_HEALTH = Health(credential="Wrangler sign-in, refreshes in 52 min")
MLX_HEALTH = Health(reason="The MLX server isn't running", detail="The model download isn't finished")


def fixture_service() -> Service:
    """A service over the real config, with fake providers that answer from the fixtures."""
    providers: dict[str, DecisionProvider] = {}
    for target in CONFIG.targets.values():
        health = WORKERS_HEALTH if target.provider == "workers-ai" else HEALTH.get(target.name, MLX_HEALTH)
        respond = respond_for(target.name) if target.name in PLANS else None
        providers[target.name] = FakeProvider(target, respond, health)
    return Service(CONFIG, providers, clock=lambda: at(3))


def service_fixtures() -> dict[str, BaseModel]:
    """The fixtures for the live routes, made by the service itself."""
    service = fixture_service()
    unchecked = service.list_targets()
    checked = asyncio.run(service.check_targets())
    goblin = CASES[0]
    single = DecideBody(state=goblin.state, questions=QUESTIONS, targets=[FOUNDRY])
    partial = DecideBody(state=goblin.state, questions=QUESTIONS, targets=[FOUNDRY, WORKERS, OLLAMA])
    return {
        "get_targets.json": checked,
        "get_targets.unchecked.json": unchecked,
        "post_targets_check.json": checked,
        "post_decide.json": asyncio.run(service.decide(single)),
        "post_decide.partial.json": asyncio.run(service.decide(partial)),
    }


def slim(result: TargetResult) -> TargetResult:
    return result.model_copy(update={"request_body": None, "raw": None})


RESULTS: dict[tuple[str, str], TargetResult] = {
    (target, case.id): make_result(target, case) for target in (FOUNDRY, WORKERS) for case in CASES
}
CACHED = {(WORKERS, "goblin-bribe"), (WORKERS, "orc-charge")}


def answer_value(question_id: str, answer: Answer) -> bool | str | int | None:
    match answer:
        case NoulAnswer():
            return answer.probability >= 0.5
        case ChoiceAnswer():
            return answer.choice
        case ScoreAnswer():
            return answer.level


def answer_probability(answer: Answer) -> float | None:
    match answer:
        case NoulAnswer():
            return answer.probability if answer.probability >= 0.5 else 1 - answer.probability
        case ChoiceAnswer():
            return answer.probabilities.get(answer.choice)
        case ScoreAnswer():
            return answer.probabilities[answer.level] if answer.level is not None else None


def is_correct(case: Case, question_id: str, answer: Answer | None) -> bool | None:
    expectation = case.expected.get(question_id)
    if expectation is None or expectation.answer is None:
        return None
    if answer is None:
        return False
    value = answer_value(question_id, answer)
    if isinstance(answer, ScoreAnswer):
        assert isinstance(value, int) and isinstance(expectation.answer, int)
        return abs(value - expectation.answer) <= expectation.tolerance
    return value == expectation.answer


# Targets


# Runs


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
        id="0142",
        kind="suite",
        suite="parley",
        question_set="parley",
        question_set_version=QUESTION_SET.version,
        policy="parley",
        policy_version=POLICY_VERSION,
        targets=RUN_TARGETS,
        repeats=1,
        variants=[],
        no_cache=False,
        baseline="0141",
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

BASELINE = run_summary(
    "0141",
    question_set_version=OLD_QUESTION_SET.version,
    baseline=None,
    counts=counts({FOUNDRY: {"sent": 4}, WORKERS: {"sent": 4}}, len(CASES), [FOUNDRY, WORKERS]),
    targets=[FOUNDRY, WORKERS],
    cost_usd=0.0000277,
    created_at=at(-30),
    started_at=at(-30),
    finished_at=at(-29.8),
)
PROBE_VARIANTS: list[ProbeVariant] = ["option_order", "key_order"]
PROBE_INSTANCES: dict[ProbeVariant, int] = {"option_order": 3, "key_order": 1}
PROBE_JOBS_PER_TARGET = len(CASES) * (1 + sum(PROBE_INSTANCES.values()))
PROBE_RUN = run_summary(
    "0143",
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
    "0144",
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


def run_events() -> str:
    tally: dict[str, dict[str, int]] = {}

    def bump(target: str, kind: str) -> RunCounts:
        row = tally.setdefault(target, {})
        row[kind] = row.get(kind, 0) + 1
        return counts(tally, len(CASES), RUN_TARGETS)

    current = counts({}, len(CASES), RUN_TARGETS)
    events: list[RunEvent] = [ProgressEvent(run_id="0142", status="running", counts=current)]
    for _ in CASES:
        current = bump(OLLAMA, "skipped")
    events.append(TargetSkippedEvent(run_id="0142", target=OLLAMA, reason=OLLAMA_REASON, counts=current))
    for case in CASES:
        for target in (FOUNDRY, WORKERS):
            cached = (target, case.id) in CACHED
            current = bump(target, "cached" if cached else "sent")
            events.append(
                ResultEvent(
                    run_id="0142",
                    case_id=case.id,
                    target=target,
                    repeat=0,
                    cached=cached,
                    result=slim(RESULTS[target, case.id]),
                    counts=current,
                )
            )
    final = run_summary("0142")
    assert current == final.counts
    events.append(FinishedEvent(run_id="0142", counts=final.counts, summary=final))
    return "".join(sse_event(index, event) for index, event in enumerate(events))


# Metrics


def question_metrics(target: str) -> list[QuestionMetrics]:
    rows: list[QuestionMetrics] = []
    for question_id, question in QUESTIONS.items():
        answers = [(case, RESULTS[target, case.id].answers[question_id]) for case in CASES]
        correct = [is_correct(case, question_id, answer) for case, answer in answers]
        accuracy = sum(1 for c in correct if c) / len(correct)
        row = QuestionMetrics(
            question=question_id,
            type=question.type,
            n=len(answers),
            accuracy=accuracy,
            macro_f1=None,
            mae=None,
            within_tolerance=None,
            brier=None,
            log_loss=None,
            auroc=None,
            ece=None,
            abstention_rate=None,
            consistency=None,
        )
        match question.type:
            case "choice":
                row.macro_f1 = 1.0 if accuracy == 1.0 else 0.667
                row.ece = choice_ece(target, question_id)
            case "noul":
                pairs = [(noul_probability(a), bool(case.expected[question_id].answer)) for case, a in answers]
                row.brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
                row.log_loss = -sum(math.log(p if y else 1 - p) for p, y in pairs) / len(pairs)
                row.auroc = 1.0
                row.ece = calibration(target, question_id).ece
            case "score":
                errors = [
                    abs(a.score - int(case.expected[question_id].answer or 0))
                    for case, a in answers
                    if isinstance(a, ScoreAnswer)
                ]
                row.mae = sum(errors) / len(errors)
                row.within_tolerance = accuracy
        rows.append(row)
    return rows


def noul_probability(answer: Answer) -> float:
    assert isinstance(answer, NoulAnswer)
    return answer.probability


def choice_ece(target: str, question_id: str) -> float:
    return calibration(target, question_id).ece or 0.0


def calibration(target: str, question_id: str, bin_count: int = 10) -> Calibration:
    pairs: list[tuple[float, bool]] = []
    for case in CASES:
        answer = RESULTS[target, case.id].answers[question_id]
        if isinstance(answer, NoulAnswer):
            pairs.append((answer.probability, bool(case.expected[question_id].answer)))
        elif isinstance(answer, ChoiceAnswer):
            pairs.append((answer.probabilities[answer.choice], answer.choice == case.expected[question_id].answer))
    bins: list[CalibrationBin] = []
    ece = 0.0
    for index in range(bin_count):
        lower, upper = index / bin_count, (index + 1) / bin_count
        members = [(p, y) for p, y in pairs if lower <= p < upper or (index == bin_count - 1 and p == 1.0)]
        mean = sum(p for p, _ in members) / len(members) if members else None
        rate = sum(1 for _, y in members if y) / len(members) if members else None
        if mean is not None and rate is not None:
            ece += len(members) / len(pairs) * abs(mean - rate)
        bins.append(
            CalibrationBin(lower=lower, upper=upper, count=len(members), mean_predicted=mean, observed_rate=rate)
        )
    return Calibration(run_id="0142", target=target, question=question_id, bins=bins, ece=ece, n=len(pairs))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def run_metrics() -> RunMetrics:
    targets: list[TargetMetrics] = []
    for target in (FOUNDRY, WORKERS):
        costs = [RESULTS[target, case.id].cost_usd for case in CASES]
        known = [cost for cost in costs if cost is not None]
        targets.append(
            TargetMetrics(
                target=target,
                results=len(CASES),
                errors=0,
                skipped=0,
                probabilities=True,
                latency_p50_ms=percentile(LATENCY[target], 0.5),
                latency_p95_ms=percentile(LATENCY[target], 0.95),
                cost_usd=sum(known) if known else None,
                cost_per_1k_usd=sum(known) / len(known) * 1000 if known else None,
                questions=question_metrics(target),
                decision=DecisionMetrics(
                    n=len(CASES),
                    accuracy=1.0 if target == FOUNDRY else 0.75,
                    decided_share=0.75 if target == FOUNDRY else 0.5,
                    error_rate=0.0 if target == FOUNDRY else 0.5,
                    cost=0.0 if target == FOUNDRY else 1.0,
                ),
            )
        )
    targets.append(
        TargetMetrics(
            target=OLLAMA,
            results=0,
            errors=0,
            skipped=len(CASES),
            probabilities=True,
            latency_p50_ms=None,
            latency_p95_ms=None,
            cost_usd=None,
            cost_per_1k_usd=None,
            questions=[],
            decision=None,
        )
    )
    return RunMetrics(run_id="0142", questions=list(QUESTIONS), targets=targets)


def confusion(target: str, question_id: str) -> ConfusionMatrix:
    question = QUESTIONS[question_id]
    assert isinstance(question, ChoiceQuestion)
    options = list(question.criteria)
    matrix = [[0] * len(options) for _ in options]
    for case in CASES:
        answer = RESULTS[target, case.id].answers[question_id]
        assert isinstance(answer, ChoiceAnswer)
        expected = case.expected[question_id].answer
        assert isinstance(expected, str)
        matrix[options.index(expected)][options.index(answer.choice)] += 1
    recall = [row[i] / sum(row) if sum(row) else None for i, row in enumerate(matrix)]
    correct = sum(matrix[i][i] for i in range(len(options)))
    return ConfusionMatrix(
        run_id="0142",
        target=target,
        question=question_id,
        options=options,
        counts=matrix,
        correct=correct,
        total=len(CASES),
        recall=recall,
    )


def mcnemar_p(fixed: int, broken: int) -> float | None:
    n = fixed + broken
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(fixed, broken) + 1)) / 2**n
    return min(1.0, 2 * tail)


# The baseline ran the older question set, which has no "wait" option, so its intent answers differ.
BASELINE_INTENT = {
    (FOUNDRY, "gnoll-watch"): ("evade", 0.712),
    (WORKERS, "kobold-retreat"): ("evade", 0.874),
    (WORKERS, "gnoll-watch"): ("evade", 0.655),
}


def run_changes() -> RunChanges:
    changes: list[AnswerChange] = []
    summary: list[ChangeSummary] = []
    for target in (FOUNDRY, WORKERS):
        fixed = broken = changed = 0
        for case in CASES:
            baseline = BASELINE_INTENT.get((target, case.id))
            if baseline is None:
                continue
            answer = RESULTS[target, case.id].answers["intent"]
            assert isinstance(answer, ChoiceAnswer)
            expected = case.expected["intent"].answer
            was = baseline[0] == expected
            now = answer.choice == expected
            status = "fixed" if now and not was else "broken" if was and not now else "changed"
            fixed += status == "fixed"
            broken += status == "broken"
            changed += status == "changed"
            changes.append(
                AnswerChange(
                    case_id=case.id,
                    target=target,
                    question="intent",
                    expected=expected,
                    baseline_answer=baseline[0],
                    baseline_probability=baseline[1],
                    answer=answer.choice,
                    probability=answer.probabilities[answer.choice],
                    status=status,
                )
            )
        summary.append(
            ChangeSummary(
                target=target, fixed=fixed, broken=broken, changed=changed, mcnemar_p=mcnemar_p(fixed, broken)
            )
        )
    return RunChanges(run_id="0142", baseline="0141", changes=changes, summary=summary)


def run_case(case_id: str) -> RunCase:
    case = CASE_BY_ID[case_id]
    results = [
        CaseResult(
            target=target,
            repeat=0,
            cached=(target, case_id) in CACHED,
            correct={qid: is_correct(case, qid, RESULTS[target, case_id].answers.get(qid)) for qid in QUESTIONS},
            result=RESULTS[target, case_id],
        )
        for target in (FOUNDRY, WORKERS)
    ]
    return RunCase(run_id="0142", case=case, questions=QUESTIONS, results=results)


def report_markdown(metrics: RunMetrics) -> str:
    lines = [
        "# Run 0142: parley",
        "",
        f"Question set `parley` version `{QUESTION_SET.version[:12]}`, 4 cases, 3 targets, baseline run 0141.",
        "",
        "| Target | Intent accuracy | Bribe Brier | Reaction MAE | p50 latency |",
        "|---|---|---|---|---|",
    ]
    for target in metrics.targets:
        by_id = {q.question: q for q in target.questions}
        if not by_id:
            lines.append(f"| {target.target} | Skipped | | | |")
            continue
        lines.append(
            f"| {target.target} | {by_id['intent'].accuracy:.2f} | {by_id['bribe'].brier:.4f} "
            f"| {by_id['reaction'].mae:.2f} | {target.latency_p50_ms:.0f} ms |"
        )
    return "\n".join(lines) + "\n"


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
    return ProbeReport(run_id="0143", variants=PROBE_VARIANTS, cells=cells, summary=summary)


# Question sets


VERSIONS = QuestionSetVersions(
    name="parley",
    versions=[
        QuestionSetVersion(version=QUESTION_SET.version, first_seen=at(5), question_count=3, run_count=2, current=True),
        QuestionSetVersion(
            version=OLD_QUESTION_SET.version, first_seen=at(-40), question_count=3, run_count=1, current=False
        ),
    ],
)
CHECKS = [
    WordingCheck(
        question="intent",
        code="no_abstention",
        message="No option for a player whose intent can't be told",
    )
]


def question_set_diff() -> QuestionSetDiff:
    diffs: list[QuestionDiff] = []
    for question_id, after in QUESTIONS.items():
        before: Question = OLD_QUESTION_SET.questions[question_id]
        if before == after:
            diffs.append(
                QuestionDiff(
                    id=question_id,
                    status="unchanged",
                    before=before,
                    after=after,
                    changed_fields=[],
                    options=[],
                    order_changed=False,
                )
            )
            continue
        assert isinstance(before, ChoiceQuestion) and isinstance(after, ChoiceQuestion)
        options = [
            OptionDiff(
                key=key,
                status="added" if key not in before.criteria else "unchanged",
                before=before.criteria.get(key),
                after=text,
            )
            for key, text in after.criteria.items()
        ]
        diffs.append(
            QuestionDiff(
                id=question_id,
                status="changed",
                before=before,
                after=after,
                changed_fields=["criteria"],
                options=options,
                order_changed=False,
            )
        )
    return QuestionSetDiff(
        name="parley", from_version=OLD_QUESTION_SET.version, to_version=QUESTION_SET.version, questions=diffs
    )


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
        policy="parley", run_id="0142", target=FOUNDRY, threshold="goodwill_threshold", current=0.6, points=points
    )


def error(code: Any, message: str, field: str | None = None, details: list[ErrorDetail] | None = None) -> ApiError:
    return ApiError(error=ApiErrorBody(code=code, message=message, field=field, details=details or []))


def build() -> dict[str, BaseModel | str]:
    """Every fixture, keyed by file name."""
    metrics = run_metrics()
    detail = QuestionSetDetail(question_set=QUESTION_SET, suites=["parley"], checks=CHECKS)
    suite_summary = SuiteSummary(
        name="parley",
        question_set="parley",
        question_set_version=QUESTION_SET.version,
        policy="parley",
        targets=SUITE.targets,
        case_count=len(CASES),
        draft_count=1,
    )
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
    return {
        **service_fixtures(),
        "post_decide.422.json": error(
            "invalid_request",
            "Unknown target: clef@nowhere",
            "targets.0",
            [ErrorDetail(field="targets.0", message="Unknown target: clef@nowhere")],
        ),
        "get_suites.json": SuiteList(suites=[suite_summary]),
        "get_suites_{name}.json": SuiteDetail(suite=SUITE, question_set=QUESTION_SET),
        "get_suites_{name}.404.json": error("not_found", "No suite named reaction"),
        "get_suites_{name}_check.json": SuiteCheck(suite="parley", valid=True, errors=[], checks=CHECKS),
        "post_suites_{name}_cases.json": CaseCreated(suite="parley", case=new_case, case_count=len(CASES) + 1),
        "post_suites_{name}_cases.409.json": error(
            "conflict", "The suite already has a case goblin-bribe", "id", [ErrorDetail(field="id", message="Taken")]
        ),
        "get_question-sets.json": QuestionSetList(
            question_sets=[
                QuestionSetSummary(
                    name="parley", version=QUESTION_SET.version, question_count=3, suites=["parley"], updated_at=at(5)
                )
            ]
        ),
        "get_question-sets_{name}.json": detail,
        "put_question-sets_{name}.json": detail,
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
        "get_question-sets_{name}_versions.json": VERSIONS,
        "get_question-sets_{name}_versions_{version}.json": OLD_QUESTION_SET,
        "get_question-sets_{name}_diff.json": question_set_diff(),
        "post_runs.json": RunCreated(id="0144"),
        "get_runs.json": RunList(runs=[CANCELLED_RUN, PROBE_RUN, run_summary("0142"), BASELINE]),
        "get_runs_{id}.json": run_summary("0142"),
        "get_runs_{id}.404.json": error("not_found", "No run 0999"),
        "get_runs_{id}_events.sse": run_events(),
        "post_runs_{id}_cancel.json": CANCELLED_RUN,
        "get_runs_{id}_metrics.json": metrics,
        "get_runs_{id}_confusion.json": confusion(WORKERS, "intent"),
        "get_runs_{id}_calibration.json": calibration(FOUNDRY, "bribe"),
        "get_runs_{id}_changes.json": run_changes(),
        "get_runs_{id}_cases_{case_id}.json": run_case("goblin-bribe"),
        "get_runs_{id}_report.json": RunReport(
            summary=run_summary("0142"), metrics=metrics, markdown=report_markdown(metrics)
        ),
        "get_runs_{id}_probes.json": probe_report(),
        "post_probes.json": RunCreated(id="0143"),
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
    for name, fixture in build().items():
        (out / name).write_text(render(fixture))


if __name__ == "__main__":
    write()
