import asyncio
import json
from pathlib import Path

import pytest

import api_fixtures
from jevtester import cli
from jevtester.errors import InvalidRequestError, NotFoundError
from jevtester.evaluate.checks import case_errors, wording_checks
from jevtester.evaluate.metrics import calibration_bins, mcnemar_p, percentile, question_metrics
from jevtester.evaluate.scoring import answer_probability, answer_value, is_correct
from jevtester.normalize import ChoiceAnswer, NoulAnswer, ScoreAnswer, TargetResult
from jevtester.schemas import RunComparison, RunCreate, SuiteCheck
from jevtester.service import Service
from jevtester.spec import (
    Case,
    ChoiceQuestion,
    Expectation,
    NoulCriteria,
    NoulQuestion,
    Question,
    QuestionSet,
    ScoreQuestion,
    Suite,
)
from jevtester.store.runs import StoredResult


def noul(p: float) -> NoulAnswer:
    return NoulAnswer(probability=p, confidence=abs(2 * p - 1))


def choice(chosen: str, **probabilities: float) -> ChoiceAnswer:
    return ChoiceAnswer(choice=chosen, probabilities=probabilities, confidence=0.5)


def score(level: int, value: float, probabilities: list[float | None]) -> ScoreAnswer:
    return ScoreAnswer(score=value, level=level, probabilities=probabilities, legend=["a", "b", "c"])


# Scoring


@pytest.mark.parametrize(
    ("expectation", "answer", "correct"),
    [
        (Expectation(answer=True), noul(0.9), True),
        (Expectation(answer=True), noul(0.5), True),
        (Expectation(answer=False), noul(0.49), True),
        (Expectation(answer=False), noul(0.8), False),
        (Expectation(answer="parley"), choice("parley", parley=0.9, fight=0.1), True),
        (Expectation(answer="parley", acceptable=["wait"]), choice("wait", parley=0.4, wait=0.6), True),
        (Expectation(answer="parley"), choice("fight", parley=0.4, fight=0.6), False),
        (Expectation(answer=2), score(1, 1.4, [0.2, 0.5, 0.3]), False),
        (Expectation(answer=2, tolerance=1), score(1, 1.4, [0.2, 0.5, 0.3]), True),
        (Expectation(answer=0, acceptable=[1]), score(1, 1.0, [0.2, 0.5, 0.3]), True),
        (Expectation(answer=True), None, False),
        (Expectation(), noul(0.9), None),
        (None, noul(0.9), None),
    ],
)
def test_is_correct(expectation: Expectation | None, answer: NoulAnswer | None, correct: bool | None) -> None:
    assert is_correct(expectation, answer) is correct


def test_answer_values_and_probabilities() -> None:
    assert (answer_value(noul(0.3)), answer_probability(noul(0.3))) == (False, pytest.approx(0.7))
    assert (answer_value(choice("a", a=0.8, b=0.2)), answer_probability(choice("a", a=0.8, b=0.2))) == ("a", 0.8)
    assert (answer_value(score(2, 1.9, [0.1, 0.2, 0.7])), answer_probability(score(2, 1.9, [0.1, 0.2, 0.7]))) == (
        2,
        0.7,
    )
    empty = ScoreAnswer(score=0.0, level=None, probabilities=[None, None], legend=["a", "b"])
    assert answer_value(empty) is None
    assert is_correct(Expectation(answer=0), empty) is False


# Metrics


def stored(
    case_id: str, answer: NoulAnswer | ChoiceAnswer | ScoreAnswer, repeat: int = 0, key: str = "q"
) -> StoredResult:
    result = TargetResult(target="t", ok=True, answers={key: answer})
    return StoredResult(case_id=case_id, target="t", repeat=repeat, cached=False, result=result)


def cases(**expected: bool | str | int) -> dict[str, Case]:
    return {
        name: Case(id=name, state="s", expected={"q": Expectation(answer=value)}) for name, value in expected.items()
    }


def test_noul_metrics() -> None:
    results = [stored("a", noul(0.9)), stored("b", noul(0.2)), stored("c", noul(0.6))]
    metrics = question_metrics(
        "q", NoulQuestion(instructions="?"), results, cases(a=True, b=False, c=False), probabilities=True
    )
    assert metrics.n == 3
    assert metrics.accuracy == pytest.approx(2 / 3)
    assert metrics.brier == pytest.approx((0.01 + 0.04 + 0.36) / 3)
    assert metrics.auroc == pytest.approx(1.0)
    assert metrics.ece is not None
    assert metrics.macro_f1 is None


def test_auroc_is_none_with_one_class() -> None:
    results = [stored("a", noul(0.9)), stored("b", noul(0.8))]
    metrics = question_metrics("q", NoulQuestion(instructions="?"), results, cases(a=True, b=True), probabilities=True)
    assert metrics.auroc is None


def test_choice_metrics_and_abstention() -> None:
    question = ChoiceQuestion(instructions="?", criteria={"x": "X", "y": "Y", "cannot_tell": "Can't tell"})
    results = [
        stored("a", choice("x", x=0.9, y=0.05, cannot_tell=0.05)),
        stored("b", choice("x", x=0.6, y=0.3, cannot_tell=0.1)),
        stored("c", choice("cannot_tell", x=0.2, y=0.2, cannot_tell=0.6)),
    ]
    metrics = question_metrics("q", question, results, cases(a="x", b="y", c="y"), probabilities=True)
    assert metrics.accuracy == pytest.approx(1 / 3)
    # x: precision 1/2, recall 1, F1 2/3. y: F1 0. cannot_tell: F1 0.
    assert metrics.macro_f1 == pytest.approx((2 / 3) / 3)
    assert metrics.abstention_rate == pytest.approx(1 / 3)


def test_choice_metrics_without_probabilities_have_no_calibration() -> None:
    question = ChoiceQuestion(instructions="?", criteria={"x": "X", "y": "Y"})
    metrics = question_metrics(
        "q", question, [stored("a", choice("x", x=1.0, y=0.0))], cases(a="x"), probabilities=False
    )
    assert metrics.ece is None
    assert metrics.abstention_rate is None


def test_score_metrics() -> None:
    question = ScoreQuestion(instructions="?", criteria=["a", "b", "c"])
    results = [stored("a", score(2, 1.8, [0.1, 0.2, 0.7])), stored("b", score(1, 1.2, [0.2, 0.5, 0.3]))]
    expected = {
        "a": Case(id="a", state="s", expected={"q": Expectation(answer=2)}),
        "b": Case(id="b", state="s", expected={"q": Expectation(answer=0, tolerance=1)}),
    }
    metrics = question_metrics("q", question, results, expected, probabilities=True)
    assert metrics.accuracy == pytest.approx(0.5)
    assert metrics.within_tolerance == pytest.approx(1.0)
    assert metrics.mae == pytest.approx((0.2 + 1.2) / 2)
    assert metrics.ece is None


def test_consistency_across_repeats() -> None:
    results = [
        stored("a", noul(0.9), 0),
        stored("a", noul(0.8), 1),
        stored("b", noul(0.6), 0),
        stored("b", noul(0.4), 1),
    ]
    metrics = question_metrics("q", NoulQuestion(instructions="?"), results, cases(a=True, b=True), probabilities=True)
    assert metrics.consistency == pytest.approx(0.5)
    single = question_metrics("q", NoulQuestion(instructions="?"), results[:1], cases(a=True), probabilities=True)
    assert single.consistency is None


def test_calibration_bins_and_ece() -> None:
    bins, ece = calibration_bins([(0.95, True), (0.95, True), (0.15, False), (0.15, True)], 10)
    assert [b.count for b in bins if b.count] == [2, 2]
    assert bins[1].observed_rate == pytest.approx(0.5)
    assert ece == pytest.approx((2 * 0.05 + 2 * 0.35) / 4)
    assert calibration_bins([], 10)[1] is None
    last, _ = calibration_bins([(1.0, True)], 10)
    assert last[-1].count == 1


@pytest.mark.parametrize(
    ("fixed", "broken", "p"), [(0, 0, None), (1, 0, 1.0), (5, 0, 0.0625), (6, 1, 0.125), (3, 3, 1.0)]
)
def test_mcnemar_exact_p(fixed: int, broken: int, p: float | None) -> None:
    assert mcnemar_p(fixed, broken) == (pytest.approx(p) if p is not None else None)


def test_percentile() -> None:
    assert percentile([], 0.5) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == pytest.approx(2.5)
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == pytest.approx(3.85)


# Checks


def test_wording_checks_find_each_problem() -> None:
    questions: dict[str, Question] = {
        "two": NoulQuestion(instructions="Is it hostile? Is it armed?"),
        "degree": ChoiceQuestion(
            instructions="?", criteria={"a": "Very angry", "b": "Somewhat calm", "cannot_tell": "x"}
        ),
        "numbers": ScoreQuestion(instructions="?", criteria=["0", "1", "2"]),
        "abstain": ChoiceQuestion(instructions="?", criteria={"a": "A", "b": "B"}),
        "same": ScoreQuestion(instructions="?", criteria=["Calm", "calm "]),
        "fine": NoulQuestion(instructions="?", criteria=NoulCriteria(true="They draw weapons")),
    }
    found = {(check.question, check.code) for check in wording_checks(QuestionSet(name="q", questions=questions))}
    assert found == {
        ("two", "multiple_dimensions"),
        ("degree", "degree_words"),
        ("numbers", "bare_number_levels"),
        ("abstain", "no_abstention"),
        ("same", "duplicate_options"),
    }


def test_case_errors_find_each_problem() -> None:
    questions = QuestionSet(
        name="q",
        questions={
            "yes": NoulQuestion(instructions="?"),
            "pick": ChoiceQuestion(instructions="?", criteria={"a": "A", "b": "B"}),
            "level": ScoreQuestion(instructions="?", criteria=["low", "high"]),
        },
    )
    suite = Suite(
        name="s",
        question_set="q",
        cases=[
            Case(
                id="one",
                state="s",
                expected={
                    "yes": Expectation(answer="maybe"),
                    "pick": Expectation(answer="c"),
                    "level": Expectation(answer=5),
                    "gone": Expectation(answer=True),
                },
            ),
            Case(id="one", state="s", expected={"pick": Expectation(answer="a", acceptable=["z"])}),
        ],
    )
    messages = [error.message for error in case_errors(suite, questions)]
    assert messages == [
        "one: a noul expects true or false, not 'maybe'",
        "one: c isn't an option",
        "one: level 5 is outside 0 to 1",
        "one expects an answer to gone, which isn't asked",
        "The case id one is used twice",
        "one: z isn't an option",
    ]


def test_the_repository_suite_passes_its_checks(tmp_path: Path) -> None:
    service = api_fixtures.fixture_service(tmp_path)
    check = service.check_suite("parley")
    assert check.valid
    assert [(c.question, c.code) for c in check.checks] == [("intent", "no_abstention")]


# The service


@pytest.fixture
def service(tmp_path: Path) -> Service:
    prepared, _ = api_fixtures.prepared_service(tmp_path)
    return prepared


def test_confusion_needs_a_choice_question(service: Service) -> None:
    with pytest.raises(InvalidRequestError, match="noul question"):
        service.run_confusion("0002", "bribe", api_fixtures.WORKERS)
    with pytest.raises(InvalidRequestError, match="didn't run"):
        service.run_confusion("0002", "intent", "clef@workers-ai")
    with pytest.raises(InvalidRequestError, match="didn't ask"):
        service.run_confusion("0002", "mood", api_fixtures.WORKERS)


def test_calibration_rejects_a_score_question_and_bad_bins(service: Service) -> None:
    with pytest.raises(InvalidRequestError, match="score question"):
        service.run_calibration("0002", "reaction", api_fixtures.WORKERS, 10)
    with pytest.raises(InvalidRequestError, match="bins"):
        service.run_calibration("0002", "intent", api_fixtures.WORKERS, 0)


def test_run_case_and_changes_need_real_ids(service: Service) -> None:
    with pytest.raises(NotFoundError):
        service.run_case("0002", "nobody")
    with pytest.raises(NotFoundError):
        service.run_changes("0002", "0999")


def test_run_case_marks_each_answer(service: Service) -> None:
    case = service.run_case("0002", "kobold-retreat")
    workers = next(row for row in case.results if row.target == api_fixtures.WORKERS)
    assert workers.correct["intent"] is False
    assert workers.correct["bribe"] is True


def test_a_run_is_scored_against_its_own_cases(service: Service) -> None:
    suite = service.files.load_suite("parley")
    edited = [case.model_copy(update={"expected": {}}) for case in suite.cases]
    service.files.save_suite(suite.model_copy(update={"cases": edited}))
    metrics = service.run_metrics("0002")
    foundry = next(t for t in metrics.targets if t.target == api_fixtures.FOUNDRY)
    assert foundry.questions[0].n == 4


def test_compare_reports_a_regression(service: Service) -> None:
    # Workers AI fixed one intent and broke one, so its accuracy held. Foundry only fixed one.
    assert service.compare_runs("0002", "0001", max_drop=0.1).regressions == []
    # Run backwards, the fix is a drop from 1.0 to 0.75.
    comparison = service.compare_runs("0001", "0002", max_drop=0.1)
    assert [(r.target, r.question, r.drop) for r in comparison.regressions] == [
        (api_fixtures.FOUNDRY, "intent", pytest.approx(0.25))
    ]
    assert service.compare_runs("0001", "0002", max_drop=0.3).regressions == []


def test_report_includes_the_changes(service: Service) -> None:
    report = service.run_report("0002")
    assert report.markdown.startswith("# Run 0002: parley")
    assert "## Changes from run 0001" in report.markdown
    assert "| kobold-retreat | clef-flash@workers-ai | intent | evade | wait | evade | broken |" in report.markdown


# The CLI


@pytest.fixture
def cli_service(service: Service, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Service:
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    monkeypatch.chdir(tmp_path)
    return service


def test_cli_compare_exits_with_1_on_a_regression(cli_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["compare", "0002", "0001"]) == 0
    out = capsys.readouterr().out
    assert "broken   kobold-retreat  clef-flash@workers-ai  intent: evade -> wait (expected evade)" in out
    assert "clef-flash@workers-ai: 1 fixed, 1 broken, 0 changed, McNemar p 1.000" in out
    assert cli.main(["compare", "0001", "0002", "--max-drop", "0.1"]) == 1
    assert "Regression: decision-1@foundry intent accuracy 1.000 -> 0.750" in capsys.readouterr().out
    assert cli.main(["compare", "0002", "0001", "--format", "json"]) == 0
    RunComparison.model_validate(json.loads(capsys.readouterr().out))


def test_cli_report_prints_markdown(cli_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["report", "0002"]) == 0
    assert capsys.readouterr().out.startswith("# Run 0002: parley\n")


def test_cli_suite_check(cli_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["suite", "check", "suites/parley.yaml"]) == 0
    assert "no_abstention  intent: No option like cannot_tell" in capsys.readouterr().out
    suite = cli_service.files.load_suite("parley")
    broken = suite.cases[0].model_copy(update={"expected": {"intent": Expectation(answer="dance")}})
    cli_service.files.save_suite(suite.model_copy(update={"cases": [broken, *suite.cases[1:]]}))
    assert cli.main(["suite", "check", "parley", "--format", "json"]) == 2
    assert not SuiteCheck.model_validate(json.loads(capsys.readouterr().out)).valid


def test_cli_compare_of_a_missing_run_exits_with_2(cli_service: Service) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["compare", "0999", "0001"])
    assert exit_info.value.code == 2


def test_runs_save_their_cases(tmp_path: Path) -> None:
    service = api_fixtures.run_service(tmp_path)

    async def go() -> str:
        created = await service.start_run(RunCreate(suite="parley", targets=[api_fixtures.FOUNDRY]))
        await service.wait_run(created.id)
        return created.id

    run_id = asyncio.run(go())
    saved = service.store.cases(run_id)
    assert saved is not None
    assert [case.id for case in saved] == [case.id for case in api_fixtures.CASES]
