import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import api_fixtures
from fakes import FakeProvider
from jevtester import cli
from jevtester.diff import diff_question_sets
from jevtester.errors import ConflictError, InvalidRequestError, NotFoundError
from jevtester.normalize import ResultError
from jevtester.providers import DecisionProvider, Health, RawResult
from jevtester.schemas import QuestionSetBody, ResultEvent, RunCreate, RunSummary
from jevtester.service import INTERRUPTED, Service
from jevtester.spec import (
    Capabilities,
    Case,
    ChoiceQuestion,
    DecisionRequest,
    NoulQuestion,
    Question,
    QuestionSet,
    ScoreQuestion,
    Target,
)
from jevtester.store.files import SuiteFiles
from jevtester.store.runs import RunStore

ROOT = Path(__file__).parent.parent
CONFIG = api_fixtures.RUN_CONFIG
FOUNDRY = CONFIG.targets["decision-1@foundry"]
WORKERS = CONFIG.targets["clef-flash@workers-ai"]
NOW = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)


def respond_ok(request: DecisionRequest, body: dict[str, Any]) -> RawResult:
    case = next(case for case in api_fixtures.CASES if case.state == request.state)
    return api_fixtures.make_raw("decision-1@foundry", case)


def make_service(tmp_path: Path, providers: dict[str, DecisionProvider] | None = None) -> Service:
    files = SuiteFiles(tmp_path / "suites")
    files.save_question_set(api_fixtures.QUESTION_SET)
    files.save_suite(SuiteFiles(ROOT / "suites").load_suite("parley"))
    files.save_policy("parley", (ROOT / "suites" / "policies" / "parley.yaml").read_text())
    store = RunStore(tmp_path / "runs.sqlite")
    fakes = providers if providers is not None else {FOUNDRY.name: FakeProvider(FOUNDRY, respond_ok)}
    return Service(CONFIG, fakes, files=files, store=store, clock=lambda: NOW)


def run(service: Service, body: RunCreate) -> RunSummary:
    async def go() -> RunSummary:
        created = await service.start_run(body)
        return await service.wait_run(created.id)

    return asyncio.run(go())


# Suite files


def test_suite_files_round_trip(tmp_path: Path) -> None:
    files = SuiteFiles(tmp_path)
    suite = SuiteFiles(ROOT / "suites").load_suite("parley")
    files.save_suite(suite)
    assert files.load_suite("parley") == suite
    files.save_question_set(api_fixtures.QUESTION_SET)
    assert files.load_question_set("parley").version == api_fixtures.QUESTION_SET.version
    assert [s.name for s in files.list_suites()] == ["parley"]


def test_the_repository_suite_is_valid() -> None:
    files = SuiteFiles(ROOT / "suites")
    suite = files.load_suite("parley")
    question_set = files.load_question_set(suite.question_set)
    for case in suite.cases:
        assert set(case.expected) <= set(question_set.questions), case.id


@pytest.mark.parametrize("name", ["../etc", "Parley", "a/b", "", ".hidden"])
def test_names_must_be_safe_file_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(InvalidRequestError):
        SuiteFiles(tmp_path).suite_path(name)


def test_a_missing_suite_is_not_found(tmp_path: Path) -> None:
    with pytest.raises(NotFoundError):
        SuiteFiles(tmp_path).load_suite("parley")


@pytest.mark.parametrize(
    ("text", "message"), [("name: [unclosed", "isn't valid YAML"), ("name: parley\n", "question_set")]
)
def test_an_invalid_suite_file_names_the_problem(tmp_path: Path, text: str, message: str) -> None:
    (tmp_path / "parley.yaml").write_text(text)
    with pytest.raises(InvalidRequestError, match=message):
        SuiteFiles(tmp_path).load_suite("parley")


def test_a_suite_file_must_match_its_name(tmp_path: Path) -> None:
    files = SuiteFiles(tmp_path)
    files.save_suite(SuiteFiles(ROOT / "suites").load_suite("parley"))
    (tmp_path / "parley.yaml").rename(tmp_path / "other.yaml")
    with pytest.raises(InvalidRequestError, match="names the suite parley"):
        files.load_suite("other")


# The store


def test_run_ids_count_up(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    assert store.next_run_id() == "0001"
    summary = api_fixtures.CANCELLED_RUN
    store.save_run(summary)
    assert store.next_run_id() == "0005"
    reopened = RunStore(tmp_path / "runs.sqlite")
    assert reopened.get_run("0004") == summary


def test_versions_are_found_by_prefix() -> None:
    store = RunStore(Path(":memory:"))
    store.record_version(api_fixtures.QUESTION_SET, NOW)
    version = api_fixtures.QUESTION_SET.version
    assert store.get_version("parley", version[:8]) is not None
    assert store.get_version("parley", version[:7]) is None
    store.record_version(api_fixtures.QUESTION_SET, datetime(2030, 1, 1, tzinfo=UTC))
    stored = store.get_version("parley", version)
    assert stored is not None
    assert stored.first_seen == NOW


# Runs


def test_a_run_records_every_result_and_a_second_run_uses_the_cache(tmp_path: Path) -> None:
    provider = FakeProvider(FOUNDRY, respond_ok)
    service = make_service(tmp_path, {FOUNDRY.name: provider})
    first = run(service, RunCreate(suite="parley", targets=[FOUNDRY.name]))
    assert first.status == "finished"
    assert (first.counts.jobs, first.counts.sent, first.counts.cached) == (4, 4, 0)
    assert len(provider.requests) == 4
    assert len(service.store.results(first.id)) == 4

    second = run(service, RunCreate(suite="parley", targets=[FOUNDRY.name]))
    assert (second.counts.sent, second.counts.cached) == (0, 4)
    assert len(provider.requests) == 4
    assert second.cost_usd == 0.0

    third = run(service, RunCreate(suite="parley", targets=[FOUNDRY.name], no_cache=True))
    assert (third.counts.sent, third.counts.cached) == (4, 0)
    assert len(provider.requests) == 8


def test_each_repeat_is_its_own_job(tmp_path: Path) -> None:
    provider = FakeProvider(FOUNDRY, respond_ok)
    summary = run(
        make_service(tmp_path, {FOUNDRY.name: provider}), RunCreate(suite="parley", repeats=2, targets=[FOUNDRY.name])
    )
    assert summary.counts.jobs == 8
    assert len(provider.requests) == 8


def test_a_target_that_is_down_is_skipped(tmp_path: Path) -> None:
    down = FakeProvider(WORKERS, health=Health(reason="Can't get a token"))
    providers: dict[str, DecisionProvider] = {FOUNDRY.name: FakeProvider(FOUNDRY, respond_ok), WORKERS.name: down}
    summary = run(make_service(tmp_path, providers), RunCreate(suite="parley"))
    rows = {row.target: row for row in summary.counts.targets}
    assert (rows[WORKERS.name].skipped, rows[WORKERS.name].skip_reason) == (4, "Can't get a token")
    assert rows[FOUNDRY.name].sent == 4
    assert summary.counts.done == summary.counts.jobs == 8
    assert down.requests == []


def test_failed_jobs_are_counted(tmp_path: Path) -> None:
    def fail(request: DecisionRequest, body: dict[str, Any]) -> RawResult:
        return RawResult(request_body=body, status=500, error=ResultError(code="server_error", message="boom"))

    summary = run(
        make_service(tmp_path, {FOUNDRY.name: FakeProvider(FOUNDRY, fail)}),
        RunCreate(suite="parley", targets=[FOUNDRY.name]),
    )
    assert (summary.counts.failed, summary.counts.sent) == (4, 0)
    assert summary.status == "finished"


class SlowProvider:
    """Counts how many requests are in flight at once, across every instance that shares a counter."""

    def __init__(self, target: Target, counter: dict[str, int], delay: float = 0.02) -> None:
        self.target = target
        self.capabilities: Capabilities = target.capabilities
        self._counter = counter
        self._delay = delay

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult:
        self._counter["now"] += 1
        self._counter["max"] = max(self._counter["max"], self._counter["now"])
        await asyncio.sleep(self._delay)
        self._counter["now"] -= 1
        return respond_ok(request, request.system_one_body(self.target.model))

    async def health_check(self) -> Health:
        return Health()


def test_targets_in_a_concurrency_group_share_one_limit(tmp_path: Path) -> None:
    counter = {"now": 0, "max": 0}
    mlx = [CONFIG.targets[name] for name in ("clef-flash-4bit@mlx", "clef-flash-8bit@mlx")]
    providers: dict[str, DecisionProvider] = {target.name: SlowProvider(target, counter) for target in mlx}
    summary = run(make_service(tmp_path, providers), RunCreate(suite="parley", targets=[t.name for t in mlx]))
    assert summary.counts.sent == 8
    assert counter["max"] == 1


def test_a_target_runs_up_to_its_concurrency(tmp_path: Path) -> None:
    counter = {"now": 0, "max": 0}
    summary = run(
        make_service(tmp_path, {WORKERS.name: SlowProvider(WORKERS, counter)}),
        RunCreate(suite="parley", targets=[WORKERS.name], repeats=3),
    )
    assert summary.counts.sent == 12
    assert counter["max"] == WORKERS.capabilities.concurrency


def test_a_run_can_be_cancelled(tmp_path: Path) -> None:
    counter = {"now": 0, "max": 0}
    service = make_service(tmp_path, {FOUNDRY.name: SlowProvider(FOUNDRY, counter, delay=10)})

    async def go() -> tuple[RunSummary, list[str]]:
        created = await service.start_run(RunCreate(suite="parley", targets=[FOUNDRY.name]))
        events: list[str] = []

        async def follow() -> None:
            async for event in service.run_events(created.id):
                events.append(event.type)

        follower = asyncio.create_task(follow())
        await asyncio.sleep(0.05)
        summary = await service.cancel_run(created.id)
        await follower
        return summary, events

    summary, events = asyncio.run(go())
    assert summary.status == "cancelled"
    assert summary.finished_at is not None
    assert events[0] == "progress"
    assert events[-1] == "cancelled"
    again = asyncio.run(service.cancel_run(summary.id))
    assert again.status == "cancelled"


def test_events_after_a_run_ends_are_progress_and_the_final_event(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    summary = run(service, RunCreate(suite="parley", targets=[FOUNDRY.name]))

    async def collect(svc: Service) -> list[str]:
        return [event.type async for event in svc.run_events(summary.id)]

    assert asyncio.run(collect(service)) == ["progress", "finished"]
    reloaded = Service(CONFIG, {}, files=service.files, store=RunStore(tmp_path / "runs.sqlite"), clock=lambda: NOW)
    assert asyncio.run(collect(reloaded)) == ["progress", "finished"]


def test_result_events_leave_out_the_bodies(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    async def go() -> list[ResultEvent]:
        created = await service.start_run(RunCreate(suite="parley", targets=[FOUNDRY.name]))
        return [event async for event in service.run_events(created.id) if isinstance(event, ResultEvent)]

    events = asyncio.run(go())
    assert len(events) == 4
    assert all(event.result.raw is None and event.result.request_body is None for event in events)
    stored = service.store.results(events[0].run_id)
    assert all(result.result.raw is not None for result in stored)


def test_an_interrupted_run_is_marked_failed(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "runs.sqlite")
    store.save_run(api_fixtures.CANCELLED_RUN.model_copy(update={"status": "running", "finished_at": None}))
    service = Service(CONFIG, {}, files=SuiteFiles(tmp_path), store=store, clock=lambda: NOW)
    summary = service.get_run(api_fixtures.CANCELLED_RUN.id)
    assert summary.status == "failed"
    assert summary.error is not None
    assert summary.error.message == INTERRUPTED


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (RunCreate(suite="missing"), NotFoundError),
        (RunCreate(suite="parley", baseline="0999"), NotFoundError),
        (RunCreate(suite="parley", question_set_version="00000000"), NotFoundError),
        (RunCreate(suite="parley", targets=["x@y"]), InvalidRequestError),
    ],
)
def test_invalid_runs_are_rejected(tmp_path: Path, body: RunCreate, error: type[Exception]) -> None:
    with pytest.raises(error):
        run(make_service(tmp_path), body)


def test_a_run_can_use_an_older_question_set_version(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.store.record_version(api_fixtures.OLD_QUESTION_SET, NOW)
    old = api_fixtures.OLD_QUESTION_SET.version
    summary = run(service, RunCreate(suite="parley", targets=[FOUNDRY.name], question_set_version=old[:10]))
    assert summary.question_set_version == old


# Question sets and cases


def test_saving_a_question_set_makes_a_new_version(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    before = service.get_question_set("parley").question_set
    questions: dict[str, Question] = {**before.questions, "hostile": NoulQuestion(instructions="Are they hostile?")}
    after = service.save_question_set("parley", QuestionSetBody(questions=questions)).question_set
    versions = service.question_set_versions("parley").versions
    assert [v.version for v in versions] == [after.version, before.version]
    assert [v.current for v in versions if v.version == after.version] == [True]
    diff = service.diff_question_set("parley", before.version, after.version)
    assert [(q.id, q.status) for q in diff.questions][-1] == ("hostile", "added")


def test_add_case_appends_and_rejects_a_duplicate(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    created = service.add_case("parley", Case(id="new-case", state="Two bugbears."))
    assert created.case_count == 5
    assert service.get_suite("parley").suite.cases[-1].id == "new-case"
    with pytest.raises(ConflictError):
        service.add_case("parley", Case(id="new-case", state="Again."))


# The diff


def question_set(**questions: Question) -> QuestionSet:
    return QuestionSet(name="q", questions=questions)


def test_diff_marks_added_changed_and_removed_options() -> None:
    before = question_set(intent=ChoiceQuestion(instructions="What?", criteria={"a": "A", "b": "B", "c": "C"}))
    after = question_set(intent=ChoiceQuestion(instructions="What now?", criteria={"b": "B2", "a": "A", "d": "D"}))
    [change] = diff_question_sets(before, after).questions
    assert change.status == "changed"
    assert change.changed_fields == ["instructions", "criteria"]
    assert change.order_changed
    assert [(o.key, o.status) for o in change.options] == [
        ("b", "changed"),
        ("a", "unchanged"),
        ("d", "added"),
        ("c", "removed"),
    ]


def test_diff_of_a_reordered_choice_is_a_change() -> None:
    before = question_set(intent=ChoiceQuestion(instructions="?", criteria={"a": "A", "b": "B"}))
    after = question_set(intent=ChoiceQuestion(instructions="?", criteria={"b": "B", "a": "A"}))
    [change] = diff_question_sets(before, after).questions
    assert (change.status, change.changed_fields, change.order_changed) == ("changed", ["criteria"], True)


def test_diff_of_score_levels_and_removed_questions() -> None:
    before = question_set(
        level=ScoreQuestion(instructions="?", criteria=["low", "high"]), gone=NoulQuestion(instructions="?")
    )
    after = question_set(level=ScoreQuestion(instructions="?", criteria=["low", "mid", "high"]))
    diff = diff_question_sets(before, after)
    assert [(q.id, q.status) for q in diff.questions] == [("level", "changed"), ("gone", "removed")]
    assert [(o.key, o.status) for o in diff.questions[0].options] == [
        ("0", "unchanged"),
        ("1", "changed"),
        ("2", "added"),
    ]


def test_diff_of_identical_sets_is_unchanged() -> None:
    same = question_set(q=NoulQuestion(instructions="?"))
    assert [q.status for q in diff_question_sets(same, same).questions] == ["unchanged"]


# The CLI


@pytest.fixture
def cli_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Service:
    service = make_service(tmp_path)
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    return service


def test_cli_run_accepts_a_suite_path(cli_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "suites/parley.yaml", "--target", FOUNDRY.name]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("Run 0001 finished: 4 jobs, 4 sent, 0 from cache")
    assert "Run 0001 started" in captured.err
    assert "4/4" in captured.err


def test_cli_run_json_is_the_run_summary(cli_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "parley", "--target", FOUNDRY.name, "--format", "json"]) == 0
    summary = RunSummary.model_validate(json.loads(capsys.readouterr().out))
    assert summary.counts.sent == 4


def test_cli_run_of_a_missing_suite_exits_with_2(cli_service: Service) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", "missing"])
    assert exit_info.value.code == 2


def test_cli_run_exits_with_3_when_nothing_answers(cli_service: Service) -> None:
    assert cli.main(["run", "parley", "--target", WORKERS.name]) == 3
