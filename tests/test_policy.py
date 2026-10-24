from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import api_fixtures
from jevtester import cli
from jevtester.errors import InvalidRequestError, NotFoundError
from jevtester.normalize import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer, TargetResult
from jevtester.policy.engine import decide, decision_metrics, sweep
from jevtester.schemas import PolicyBody, SweepBody
from jevtester.service import Service
from jevtester.spec import Case, ChoiceQuestion, NoulQuestion, Question, ScoreQuestion
from jevtester.spec.policy import Policy
from jevtester.store.files import parse_policy
from jevtester.store.runs import StoredResult

ROOT = Path(__file__).parent.parent
POLICY_TEXT = (ROOT / "suites" / "policies" / "parley.yaml").read_text()

QUESTIONS: dict[str, Question] = {
    "intent": ChoiceQuestion(instructions="?", criteria={"parley": "P", "fight": "F", "wait": "W", "cannot_tell": "C"}),
    "bribe": NoulQuestion(instructions="?"),
    "reaction": ScoreQuestion(instructions="?", criteria=["0", "1", "2", "3", "4"]),
}


def policy(**changes: Any) -> Policy:
    data: dict[str, Any] = {
        "name": "p",
        "thresholds": {"act": 0.8, "confirm": 0.5, "goodwill": 0.6},
        "per_target": {"t2": {"goodwill": 0.4}},
        "bands": {"intent": {"act": "act", "confirm": "confirm"}},
        "composites": {"goodwill": {"bribe": 0.5, "reaction": 0.5}},
        "rules": [
            {"action": "battle", "when": {"intent": "fight"}},
            {"action": "hold", "when": {"intent": ["wait", "cannot_tell"]}},
            {"action": "deal", "when": {"intent": "parley", "goodwill": {"at_least": "goodwill"}}},
            {"action": "no_deal", "when": {"intent": "parley", "bribe": False}},
        ],
        "default": "ask",
        "costs": {"deal": {"battle": 5}},
    }
    data.update(changes)
    return Policy.model_validate(data)


def intent(choice: str, confidence: float) -> ChoiceAnswer:
    return ChoiceAnswer(choice=choice, probabilities={choice: 0.9}, confidence=confidence)


def answers(
    choice: str = "parley", confidence: float = 0.9, bribe: float = 0.9, score: float = 3.0
) -> dict[str, Answer]:
    return {
        "intent": intent(choice, confidence),
        "bribe": NoulAnswer(probability=bribe, confidence=abs(2 * bribe - 1)),
        "reaction": ScoreAnswer(score=score, level=round(score), probabilities=[0.2] * 5, legend=["x"] * 5),
    }


# The format


def test_the_repository_policy_is_valid() -> None:
    parsed = parse_policy(POLICY_TEXT, "parley")
    assert parsed.actions == ["battle", "evade", "wait", "escalate", "parley_succeeds", "parley_fails"]
    assert parsed.threshold("goodwill", "clef-flash@workers-ai") == 0.5
    assert parsed.threshold("goodwill", "decision-1@foundry") == 0.55


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"bands": {"intent": {"act": "high", "confirm": 0.5}}}, "unknown threshold high"),
        ({"per_target": {"t": {"nope": 1.0}}}, "unknown thresholds: nope"),
        ({"rules": [{"action": "a", "when": {"x": {"at_most": "nope"}}}]}, "unknown threshold nope"),
        ({"composites": {"goodwill": {"goodwill": 1.0}}}, "share a name with a question"),
        ({"rules": []}, "at least 1 item"),
    ],
)
def test_invalid_policies_are_rejected(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        policy(**changes)


def test_the_version_ignores_the_name_and_layout() -> None:
    first = parse_policy(POLICY_TEXT, "parley")
    plain = "\n".join(line for line in POLICY_TEXT.splitlines() if not line.lstrip().startswith("#"))
    assert parse_policy(plain, "parley").version == first.version
    renamed = Policy.model_validate({**first.model_dump(mode="json"), "name": "other"})
    assert renamed.version == first.version
    changed = Policy.model_validate({**first.model_dump(mode="json"), "default": "ask"})
    assert changed.version != first.version


def test_parse_policy_lists_every_error() -> None:
    text = 'name: p\nthresholds: {goodwill: high}\nrules:\n  - action: ""\n'
    with pytest.raises(InvalidRequestError) as raised:
        parse_policy(text, "p")
    assert [detail.field for detail in raised.value.details or []] == ["thresholds.goodwill", "rules.0.action"]
    with pytest.raises(InvalidRequestError, match="Line 3") as syntax:
        parse_policy("name: p\nrules:\n  - action: a: b\n", "p")
    assert [detail.line for detail in syntax.value.details or []] == [3]
    with pytest.raises(InvalidRequestError, match="named p, not q"):
        parse_policy("name: p\nrules: [{action: a}]\n", "q")


# Decisions


@pytest.mark.parametrize(
    ("given", "action", "band", "rule"),
    [
        (answers("fight"), "battle", "act", 0),
        (answers("wait", confidence=0.6), "hold", "confirm", 1),
        (answers("cannot_tell"), "hold", "act", 1),
        (answers("parley", bribe=0.9, score=3.0), "deal", "act", 2),
        (answers("parley", bribe=0.2, score=1.0), "no_deal", "act", 3),
        (answers("parley", bribe=0.6, score=0.0), "ask", "act", None),
    ],
)
def test_decide(given: dict[str, Answer], action: str, band: str, rule: int | None) -> None:
    decision = decide(policy(), QUESTIONS, given)
    assert (decision.action, decision.band, decision.rule, decision.escalated) == (action, band, rule, False)


def test_a_low_confidence_escalates() -> None:
    decision = decide(policy(), QUESTIONS, answers("fight", confidence=0.4))
    assert (decision.action, decision.band, decision.escalated) == ("escalate", "escalate", True)
    assert decision.reason == "intent confidence 0.400 is below 0.5"


def test_a_missing_banded_answer_escalates() -> None:
    given = answers()
    del given["intent"]
    decision = decide(policy(), QUESTIONS, given)
    assert decision.escalated
    assert decision.reason == "intent has no answer"


def test_composites_normalize_each_answer() -> None:
    decision = decide(policy(), QUESTIONS, answers(bribe=0.8, score=2.0))
    assert decision.composites["goodwill"] == pytest.approx(0.5 * 0.8 + 0.5 * 0.5)
    given = answers()
    del given["bribe"]
    assert decide(policy(), QUESTIONS, given).composites["goodwill"] is None


def test_per_target_thresholds_and_overrides() -> None:
    given = answers(bribe=0.6, score=1.0)  # goodwill 0.425
    assert decide(policy(), QUESTIONS, given).action == "ask"
    assert decide(policy(), QUESTIONS, given, target="t2").action == "deal"
    assert decide(policy(), QUESTIONS, given, overrides={"goodwill": 0.4}).action == "deal"


def stored(case_id: str, given: dict[str, Answer] | None, target: str = "t") -> StoredResult:
    result = TargetResult(target=target, ok=given is not None, answers=given or {})
    return StoredResult(case_id=case_id, target=target, repeat=0, cached=False, result=result)


CASES = {
    "a": Case(id="a", state="s", expected_action="battle"),
    "b": Case(id="b", state="s", expected_action="deal"),
    "c": Case(id="c", state="s", expected_action="deal"),
    "d": Case(id="d", state="s", expected_action="hold"),
    "e": Case(id="e", state="s"),
}


def test_decision_metrics() -> None:
    results = [
        stored("a", answers("fight")),  # right
        stored("b", answers("fight")),  # wrong: battle for deal costs 5
        stored("c", answers("parley", confidence=0.3)),  # escalated: costs 1
        stored("d", None),  # failed: counts as escalated, costs 1
        stored("e", answers("fight")),  # no expected action
    ]
    metrics = decision_metrics(policy(), QUESTIONS, results, CASES)
    assert metrics.n == 4
    assert metrics.accuracy == pytest.approx(0.25)
    assert metrics.decided_share == pytest.approx(0.5)
    assert metrics.error_rate == pytest.approx(0.5)
    assert metrics.cost == pytest.approx(5 + 1 + 1)
    assert decision_metrics(policy(costs=None), QUESTIONS, results, CASES).cost is None
    assert decision_metrics(policy(), QUESTIONS, [], CASES).accuracy is None


def test_sweep_moves_one_threshold() -> None:
    results = [stored("b", answers(bribe=0.6, score=2.0)), stored("c", answers(bribe=0.9, score=3.0))]
    points = sweep(policy(), "goodwill", [0.5, 0.6, 0.7, 0.8], QUESTIONS, results, CASES)
    # Goodwill is 0.55 for b and 0.825 for c.
    assert [point.error_rate for point in points] == [0.0, 0.5, 0.5, 0.5]
    assert [point.decided_share for point in points] == [1.0, 1.0, 1.0, 1.0]


# The service


@pytest.fixture
def service(tmp_path: Path) -> Service:
    prepared, _ = api_fixtures.prepared_service(tmp_path)
    return prepared


def test_runs_record_and_measure_their_policy(service: Service) -> None:
    summary = service.get_run(api_fixtures.RUN)
    assert summary.policy == "parley"
    assert summary.policy_version == api_fixtures.POLICY_VERSION
    metrics = service.run_metrics(api_fixtures.RUN)
    foundry = next(t for t in metrics.targets if t.target == api_fixtures.FOUNDRY)
    assert foundry.decision is not None
    assert foundry.decision.accuracy == 1.0
    case = service.run_case(api_fixtures.RUN, "kobold-retreat")
    workers = next(r for r in case.results if r.target == api_fixtures.WORKERS)
    assert workers.decision is not None
    assert workers.decision.escalated


def test_a_run_keeps_its_policy_after_the_file_changes(service: Service) -> None:
    edited = POLICY_TEXT.replace("act: 0.8\n  confirm: 0.5", "act: 0.99\n  confirm: 0.99")
    service.save_policy("parley", PolicyBody(yaml=edited))
    foundry = next(t for t in service.run_metrics(api_fixtures.RUN).targets if t.target == api_fixtures.FOUNDRY)
    assert foundry.decision is not None
    assert foundry.decision.decided_share == 1.0


def test_save_policy_keeps_comments_and_rejects_bad_text(service: Service) -> None:
    detail = service.save_policy("other", PolicyBody(yaml=POLICY_TEXT.replace("name: parley", "name: other")))
    assert detail.name == "other"
    saved = service.files.policy_path("other").read_text()
    assert saved.startswith("# Turns the parley questions")
    with pytest.raises(InvalidRequestError):
        service.save_policy("broken", PolicyBody(yaml="name: broken\nrules: []\n"))
    assert not service.files.policy_path("broken").exists()
    assert [p.name for p in service.list_policies().policies] == ["other", "parley"]


def test_sweep_checks_its_inputs(service: Service) -> None:
    def body(**changes: Any) -> SweepBody:
        values: dict[str, Any] = {"run_id": api_fixtures.RUN, "target": api_fixtures.FOUNDRY, "threshold": "goodwill"}
        return SweepBody.model_validate(values | changes)

    result = service.sweep_policy("parley", body(start=0.5, stop=0.6, step=0.05))
    assert [point.value for point in result.points] == [0.5, 0.55, 0.6]
    assert result.current == 0.55
    with pytest.raises(InvalidRequestError, match="no threshold"):
        service.sweep_policy("parley", body(threshold="nope"))
    with pytest.raises(InvalidRequestError, match="limit is 1000"):
        service.sweep_policy("parley", body(stop=100.0, step=0.01))
    with pytest.raises(InvalidRequestError, match="didn't run"):
        service.sweep_policy("parley", body(target="clef@workers-ai"))
    with pytest.raises(NotFoundError):
        service.sweep_policy("missing", body())


def test_suite_check_reports_a_policy_that_reads_unknown_questions(service: Service) -> None:
    text = POLICY_TEXT.replace("intent: {act: act, confirm: confirm}", "mood: {act: act, confirm: confirm}")
    service.save_policy("parley", PolicyBody(yaml=text))
    check = service.check_suite("parley")
    assert not check.valid
    assert [error.message for error in check.errors] == ["The policy reads mood, which the question set doesn't ask"]


def test_report_shows_the_decisions(service: Service) -> None:
    markdown = service.run_report(api_fixtures.RUN).markdown
    assert "## Decisions with policy `parley`" in markdown
    assert "| decision-1@foundry | 4 | 1.000 | 1.000 | 0.000 | 0.0 |" in markdown


def test_cli_policy_sweep(
    service: Service, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    args = ["policy", "sweep", "parley", "--run", "0002", "--target", api_fixtures.FOUNDRY, "--threshold", "goodwill"]
    assert cli.main([*args, "--start", "0.7", "--stop", "0.8", "--step", "0.1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "parley goodwill on decision-1@foundry, run 0002 (now 0.550)"
    assert out[2].split() == ["0.7", "1.000", "0.000", "0.000"]
    assert out[3].split() == ["0.8", "1.000", "0.250", "2.000"]
