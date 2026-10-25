import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute

import api_fixtures
from jevtester import cli
from jevtester.api import HOST, PORT, router
from jevtester.schemas import CaseCreated, QuestionSetBody
from jevtester.service import Service
from jevtester.spec import ChoiceQuestion

# Each CLI command, a command line that parses, and the route that does the same thing, as docs/reference/cli.md
# lists them.
COMMANDS: dict[str, tuple[list[str], tuple[str, str]]] = {
    "decide": (["decide", "--state", "s", "--question", "?"], ("POST", "/api/decide")),
    "targets list": (["targets", "list"], ("GET", "/api/targets")),
    "targets check": (["targets", "check"], ("POST", "/api/targets/check")),
    "run": (["run", "parley"], ("POST", "/api/runs")),
    "compare": (["compare", "0002", "0001"], ("GET", "/api/runs/{id}/compare")),
    "report": (["report", "0002"], ("GET", "/api/runs/{id}/report")),
    "probe": (["probe", "parley"], ("POST", "/api/probes")),
    "case add": (["case", "add", "parley", "--id", "x", "--state", "s"], ("POST", "/api/suites/{name}/cases")),
    "suite check": (["suite", "check", "parley"], ("GET", "/api/suites/{name}/check")),
    "policy sweep": (
        ["policy", "sweep", "parley", "--run", "1", "--target", "t", "--threshold", "x"],
        ("POST", "/api/policies/{name}/sweep"),
    ),
}
ROUTES = {
    (method, route.path) for route in router.routes if isinstance(route, APIRoute) for method in route.methods or []
}


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_every_cli_command_has_a_matching_route(command: str) -> None:
    argv, route = COMMANDS[command]
    cli.build_parser().parse_args(argv)
    assert route in ROUTES


def test_the_plan_lists_every_command() -> None:
    plan = (Path(__file__).parent.parent / "docs" / "plan.md").read_text()
    for command in ("decide", "targets list", "targets check", "run", "compare", "report", "probe", "case add"):
        assert f"`jevtester {command}" in plan
        assert command in COMMANDS


def test_serve_binds_to_this_machine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    service = api_fixtures.fixture_service(tmp_path)
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    assert cli.main(["serve"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8640}]
    assert (HOST, PORT) == ("127.0.0.1", 8640)


# Case add


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Service:
    prepared = api_fixtures.fixture_service(tmp_path)
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: prepared))
    monkeypatch.chdir(tmp_path)
    return prepared


def test_case_add_from_flags(service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["case", "add", "suites/parley.yaml", "--id", "troll-toll", "--state", "A troll blocks the bridge."]
    argv += [
        "--expect",
        "intent=parley",
        "--expect",
        "bribe=true",
        "--expect",
        "reaction=2",
        "--tolerance",
        "reaction=1",
    ]
    argv += ["--expected-action", "parley_succeeds", "--tag", "bribe"]
    assert cli.main(argv) == 0
    assert capsys.readouterr().out == "Added case troll-toll to suite parley (5 cases)\n"
    case = service.files.load_suite("parley").cases[-1]
    assert case.id == "troll-toll"
    assert {key: (e.answer, e.tolerance) for key, e in case.expected.items()} == {
        "intent": ("parley", 0),
        "bribe": (True, 0),
        "reaction": (2, 1),
    }
    assert (case.expected_action, case.tags) == ("parley_succeeds", ["bribe"])


def test_case_add_promotes_a_decide_call(service: Service, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    decided = tmp_path / "decide.json"
    decided.write_text((Path(__file__).parent / "fixtures" / "api" / "post_decide.json").read_text())
    argv = ["case", "add", "parley", "--id", "promoted", "--from-decide", str(decided)]
    argv += ["--expect-from", "decision-1@foundry", "--expect", "reaction=3", "--format", "json"]
    assert cli.main(argv) == 0
    created = CaseCreated.model_validate(json.loads(capsys.readouterr().out))
    assert created.case.state == api_fixtures.CASES[0].state
    assert {key: e.answer for key, e in created.case.expected.items()} == {
        "intent": "parley",
        "bribe": True,
        "reaction": 3,
    }


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--state", "s", "--from-decide", "x.json"],
        ["--state", "s", "--expect-from", "decision-1@foundry"],
        ["--state", "s", "--expect", "nameless"],
        ["--state", "s", "--tolerance", "reaction=lots"],
        ["--id", "goblin-bribe", "--state", "s"],
        ["--state", "s", "--expect", "bribe=maybe"],
        ["--state", "s", "--expect", "reaction=high"],
        ["--state", "s", "--expect", "mood=calm"],
    ],
)
def test_case_add_rejects_bad_input(service: Service, extra: list[str]) -> None:
    argv = ["case", "add", "parley", *(["--id", "new"] if "--id" not in extra else []), *extra]
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2


def test_case_add_reads_each_answer_by_its_question_type(service: Service) -> None:
    questions = service.get_question_set("parley").question_set.questions
    intent = questions["intent"]
    assert isinstance(intent, ChoiceQuestion)
    renamed = {**questions, "intent": intent.model_copy(update={"criteria": {"yes": "Talk", "2": "Fight"}})}
    service.save_question_set("parley", QuestionSetBody(questions=renamed))
    argv = ["case", "add", "parley", "--id", "named", "--state", "s", "--expect", "intent=yes"]
    assert cli.main([*argv, "--expect", "bribe=no", "--expect", "reaction=1"]) == 0
    case = service.files.load_suite("parley").cases[-1]
    assert {key: e.answer for key, e in case.expected.items()} == {"intent": "yes", "bribe": False, "reaction": 1}
    assert cli.main(["case", "add", "parley", "--id", "digit", "--state", "s", "--expect", "intent=2"]) == 0
    assert service.files.load_suite("parley").cases[-1].expected["intent"].answer == "2"
