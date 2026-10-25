import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jevtester import cli
from jevtester.normalize import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    choice_confidence,
    cost_usd,
    normalize,
    noul_confidence,
)
from jevtester.normalize.answers import ResultError, Usage
from jevtester.providers import RawResult, target_result
from jevtester.service import CONFIG_ENV, config_paths
from jevtester.spec import (
    Capabilities,
    Case,
    ChoiceQuestion,
    ConfigError,
    DecisionRequest,
    NoulQuestion,
    QuestionSet,
    ScoreQuestion,
    load_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "systemone"
ROOT = Path(__file__).parent.parent


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def parley_request() -> DecisionRequest:
    body = load_fixture("parley_request.json")
    return DecisionRequest.model_validate({"state": body["state"], "questions": body["questions"]})


def test_request_serializes_to_the_plan_request(parley_request: DecisionRequest) -> None:
    expected = load_fixture("parley_request.json")
    body = parley_request.system_one_body("decision-1")
    assert body == expected
    # Option order and question order carry meaning, so the body keeps them.
    assert json.dumps(body) == json.dumps(expected)


def test_request_body_omits_unset_noul_criteria() -> None:
    request = DecisionRequest(
        state="Six goblins block the stairs.", questions={"hostile": NoulQuestion(instructions="Hostile?")}
    )
    assert request.system_one_body("m")["questions"] == {"hostile": {"type": "noul", "instructions": "Hostile?"}}


def test_request_body_adds_extra_fields() -> None:
    request = DecisionRequest(state="s", questions={"q": NoulQuestion(instructions="?")})
    assert request.system_one_body("m", extra={"truncate": False})["truncate"] is False


def test_question_types_parse_by_discriminator(parley_request: DecisionRequest) -> None:
    questions = parley_request.questions
    assert isinstance(questions["intent"], ChoiceQuestion)
    assert isinstance(questions["bribe"], NoulQuestion)
    assert isinstance(questions["reaction"], ScoreQuestion)


@pytest.mark.parametrize(
    "question",
    [
        {"type": "choice", "instructions": "?", "criteria": {"only": "One option"}},
        {"type": "score", "instructions": "?", "criteria": ["One level"]},
        {"type": "box", "instructions": "?"},
        {"type": "noul", "instructions": "?", "criteria": {"maybe": "x"}},
    ],
)
def test_invalid_questions_are_rejected(question: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DecisionRequest.model_validate({"state": "s", "questions": {"q": question}})


def test_request_needs_at_least_one_question() -> None:
    with pytest.raises(ValidationError):
        DecisionRequest(state="s", questions={})


def test_question_set_version_tracks_content_and_order(parley_request: DecisionRequest) -> None:
    questions = parley_request.questions
    first = QuestionSet(name="parley", questions=questions)
    renamed = QuestionSet(name="other", questions=questions)
    assert first.version == renamed.version
    assert len(first.version) == 64

    intent = questions["intent"]
    assert isinstance(intent, ChoiceQuestion)
    reordered = intent.model_copy(update={"criteria": dict(reversed(intent.criteria.items()))})
    changed = QuestionSet(name="parley", questions={**questions, "intent": reordered})
    assert changed.version != first.version


def test_case_defaults() -> None:
    case = Case(id="goblin-bribe", state="Six goblins.")
    assert case.images == []
    assert case.expected == {}
    assert case.provenance == "human"


def test_normalizes_the_foundry_response(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    answers, warnings = normalize(parley_request.questions, body)

    assert warnings == []
    assert list(answers) == ["intent", "bribe", "reaction"]

    intent = answers["intent"]
    assert isinstance(intent, ChoiceAnswer)
    assert intent.choice == "parley"
    # Probabilities follow the question's option order, not the server's.
    assert list(intent.probabilities) == ["parley", "evade", "fight", "wait"]
    assert intent.probabilities["parley"] == pytest.approx(0.9996146903453894)
    assert intent.server_confidence == pytest.approx(0.9994862537938526)
    assert intent.confidence == pytest.approx(intent.server_confidence, abs=1e-9)

    bribe = answers["bribe"]
    assert isinstance(bribe, NoulAnswer)
    assert bribe.probability == pytest.approx(0.9988304895647238)
    assert bribe.confidence == pytest.approx(0.9976609791294476)
    assert bribe.server_confidence is None

    reaction = answers["reaction"]
    assert isinstance(reaction, ScoreAnswer)
    assert reaction.score == pytest.approx(2.20874314700501)
    assert reaction.probabilities == pytest.approx([0.0332013, 0.1910604, 0.4583301, 0.1686102, 0.1487980], abs=1e-6)
    assert reaction.level == 2
    assert reaction.legend[0] == "Attack at once"
    assert len(reaction.legend) == 5
    assert reaction.confidence is None
    assert reaction.server_confidence == pytest.approx(0.32291261419799433)


def test_normalize_flags_an_unknown_choice(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    answers_body = body["answers"]
    assert isinstance(answers_body, dict)
    answers_body["intent"]["choice"] = "dance"
    answers, warnings = normalize(parley_request.questions, body)
    assert [w.code for w in warnings] == ["unknown_option"]
    assert "intent" in answers


def test_normalize_flags_a_missing_answer(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    answers_body = body["answers"]
    assert isinstance(answers_body, dict)
    del answers_body["bribe"]
    answers, warnings = normalize(parley_request.questions, body)
    assert [(w.code, w.question) for w in warnings] == [("missing_answer", "bribe")]
    assert "bribe" not in answers


def test_normalize_flags_a_mismatched_type(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    answers_body = body["answers"]
    assert isinstance(answers_body, dict)
    answers_body["bribe"] = {"type": "choice", "choice": "yes", "probabilities": {"yes": 1.0}, "confidence": 1.0}
    answers, warnings = normalize(parley_request.questions, body)
    assert [w.code for w in warnings] == ["invalid_answer"]
    assert "bribe" not in answers


def test_normalize_marks_missing_score_levels(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    answers_body = body["answers"]
    assert isinstance(answers_body, dict)
    del answers_body["reaction"]["probabilities"]["4"]
    answers, warnings = normalize(parley_request.questions, body)
    reaction = answers["reaction"]
    assert isinstance(reaction, ScoreAnswer)
    assert reaction.probabilities[4] is None
    assert reaction.level == 2
    assert [w.code for w in warnings] == ["missing_probability"]


@pytest.mark.parametrize(("probability", "expected"), [(0.5, 0.0), (1.0, 1.0), (0.0, 1.0), (0.75, 0.5)])
def test_noul_confidence(probability: float, expected: float) -> None:
    assert noul_confidence(probability) == pytest.approx(expected)


def test_choice_confidence() -> None:
    assert choice_confidence({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}) == pytest.approx(0.0)
    assert choice_confidence({"a": 1.0, "b": 0.0}) == pytest.approx(1.0)
    assert choice_confidence({"a": 0.7, "b": 0.3}) == pytest.approx(0.4)


def test_cost_uses_input_tokens() -> None:
    capabilities = Capabilities(input_cost_per_mtok_usd=0.038)
    assert cost_usd(Usage(input_tokens=1_000_000, output_tokens=0), capabilities) == pytest.approx(0.038)
    assert cost_usd(Usage(input_tokens=None, output_tokens=None), capabilities) is None
    assert cost_usd(Usage(input_tokens=10, output_tokens=0), Capabilities()) is None


def test_config_loads_every_target() -> None:
    config = load_config(ROOT / "jevtester.toml")
    foundry = config.targets["decision-1@foundry"]
    assert foundry.name == "decision-1@foundry"
    assert foundry.provider == "systemone"
    assert foundry.capabilities.requests_per_minute == 100
    assert config.targets["clef-flash@workers-ai"].capabilities.truncates_state
    assert set(config.defaults.targets) <= set(config.targets)


def test_config_paths_default_to_the_shared_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    assert config_paths() == [Path("jevtester.toml")]


def test_config_paths_put_a_local_file_over_the_shared_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    (tmp_path / "jevtester.toml").write_text("")
    (tmp_path / "jevtester.local.toml").write_text("")
    assert config_paths() == [Path("jevtester.toml"), Path("jevtester.local.toml")]


def test_config_paths_use_a_local_file_alone_without_a_shared_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    (tmp_path / "jevtester.local.toml").write_text("")
    assert config_paths() == [Path("jevtester.local.toml")]


def test_config_paths_env_wins_over_a_local_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "jevtester.toml").write_text("")
    (tmp_path / "jevtester.local.toml").write_text("")
    monkeypatch.setenv(CONFIG_ENV, "other.toml")
    assert config_paths() == [Path("other.toml")]


def test_a_local_config_merges_over_the_shared_config(tmp_path: Path) -> None:
    shared = tmp_path / "jevtester.toml"
    shared.write_text((ROOT / "jevtester.toml").read_text())
    local = tmp_path / "jevtester.local.toml"
    local.write_text(
        "[defaults]\n"
        'targets = ["clef-flash@workers-ai"]\n'
        "[cloudflare]\n"
        'account_id = "local-account"\n'
        '[targets."decision-1@foundry"]\n'
        'base_url = "https://mine.services.ai.azure.com/providers/microsoft"\n'
        '[targets."decision-1@foundry".capabilities]\n'
        "concurrency = 2\n"
    )
    config = load_config(shared, local)
    alone = load_config(shared)
    foundry = config.targets["decision-1@foundry"]
    assert foundry.base_url == "https://mine.services.ai.azure.com/providers/microsoft"
    assert foundry.capabilities.concurrency == 2
    assert foundry.capabilities.requests_per_minute == 100
    assert foundry.label == alone.targets["decision-1@foundry"].label
    assert config.defaults.targets == ["clef-flash@workers-ai"]
    assert config.defaults.timeout_s == alone.defaults.timeout_s
    assert config.cloudflare.account_id == "local-account"
    assert list(config.targets) == list(alone.targets)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"[defaults\n", "isn't valid TOML"),
        (b'[cloudflare]\naccount_id = "\xff"\n', "isn't UTF-8 text"),
    ],
)
def test_config_rejects_a_file_that_isnt_toml(tmp_path: Path, content: bytes, message: str) -> None:
    path = tmp_path / "jevtester.toml"
    path.write_bytes(content)
    with pytest.raises(ConfigError, match=message) as raised:
        load_config(path)
    assert str(path) in str(raised.value)


def test_config_reports_a_file_it_cant_read(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"Can.t read .*missing\.toml: No such file or directory"):
        load_config(tmp_path / "missing.toml")
    with pytest.raises(ConfigError, match="Can't read"):
        load_config(tmp_path)


def test_config_rejects_a_systemone_target_without_base_url(tmp_path: Path) -> None:
    path = tmp_path / "jevtester.toml"
    path.write_text('[targets."x@y"]\nprovider = "systemone"\nmodel = "x"\nlabel = "X"\n')
    with pytest.raises(ValidationError, match="a systemone target needs base_url"):
        load_config(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"[defaults\n", "isn't valid TOML"),
        (b"\xff\xfe", "isn't UTF-8 text"),
        (b'[targets."x@y"]\nprovider = "systemone"\nmodel = "x"\nlabel = "X"\n', "targets.x@y"),
    ],
)
def test_cli_reports_a_bad_config_with_exit_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes, message: str
) -> None:
    path = tmp_path / "bad.toml"
    path.write_bytes(content)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--config", str(path), "targets", "list"])
    assert exit_info.value.code == 2
    error = capsys.readouterr().err
    assert error.startswith("jevtester: ")
    assert message in error
    assert "Traceback" not in error


def test_cli_reports_a_missing_config_with_exit_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--config", str(tmp_path / "missing.toml"), "targets", "list"])
    assert exit_info.value.code == 2
    assert "missing.toml: No such file or directory" in capsys.readouterr().err


def test_config_rejects_unknown_target_fields(tmp_path: Path) -> None:
    path = tmp_path / "jevtester.toml"
    path.write_text('[targets."x@y"]\nprovider = "systemone"\nmodel = "x"\nlabel = "X"\nbase_urll = "typo"\n')
    with pytest.raises(ValidationError):
        load_config(path)


def test_config_rejects_unknown_default_target(tmp_path: Path) -> None:
    path = tmp_path / "jevtester.toml"
    path.write_text('[defaults]\ntargets = ["missing@nowhere"]\n')
    with pytest.raises(ValidationError):
        load_config(path)


def test_target_result_from_a_raw_result(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    raw = RawResult(
        request_body=parley_request.system_one_body("decision-1"),
        status=200,
        response_body=body,
        system_one=body,
        latency_ms=1550.0,
    )
    result = target_result("decision-1@foundry", parley_request, raw, Capabilities(input_cost_per_mtok_usd=0.04))
    assert result.ok
    assert result.error is None
    assert result.usage.input_tokens == 185
    assert result.cost_usd == pytest.approx(185 * 0.04 / 1_000_000)
    assert list(result.answers) == ["intent", "bribe", "reaction"]
    assert result.raw == body


def test_target_result_keeps_a_provider_error(parley_request: DecisionRequest) -> None:
    raw = RawResult(
        request_body={},
        status=401,
        response_body={"error": "denied"},
        error=ResultError(code="auth", message="The token was rejected.", status=401),
    )
    result = target_result("decision-1@foundry", parley_request, raw, Capabilities())
    assert not result.ok
    assert result.answers == {}
    assert result.error is not None
    assert result.error.code == "auth"


def test_target_result_without_answers_is_an_invalid_response(parley_request: DecisionRequest) -> None:
    raw = RawResult(request_body={}, status=200, response_body={"model": "m"}, system_one={"model": "m"})
    result = target_result("x", parley_request, raw, Capabilities())
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "invalid_response"


def test_every_capability_field_serializes() -> None:
    dumped = Capabilities().model_dump(mode="json")
    assert set(dumped) == set(Capabilities.model_fields)
    assert dumped["context_window"] is None


def test_score_level_ties_go_to_the_lower_level() -> None:
    question = ScoreQuestion(instructions="?", criteria=["low", "mid", "high"])
    body = {"answers": {"q": {"type": "score", "score": 1.0, "probabilities": {"0": 0.1, "1": 0.45, "2": 0.45}}}}
    answers, _ = normalize({"q": question}, body)
    answer = answers["q"]
    assert isinstance(answer, ScoreAnswer)
    assert answer.level == 1


def test_unexpected_answers_keep_the_response_order(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    extra = {"type": "noul", "noul": 0.5}
    body["answers"] = {"zeta": extra, **body["answers"], "alpha": extra, "mid": extra}
    _, warnings = normalize(parley_request.questions, body)
    assert [w.question for w in warnings] == ["zeta", "alpha", "mid"]


def test_unknown_choice_probability_is_kept(parley_request: DecisionRequest) -> None:
    body = load_fixture("parley_response_foundry.json")
    body["answers"]["intent"]["probabilities"]["dance"] = 0.2
    answers, _ = normalize(parley_request.questions, body)
    intent = answers["intent"]
    assert isinstance(intent, ChoiceAnswer)
    assert intent.unknown_probabilities == {"dance": 0.2}
    assert "dance" not in intent.probabilities


def test_question_set_round_trips_with_its_version(parley_request: DecisionRequest) -> None:
    saved = QuestionSet(name="parley", questions=parley_request.questions)
    loaded = QuestionSet.model_validate_json(saved.model_dump_json())
    assert loaded == saved
    stale = {**saved.model_dump(mode="json"), "version": "stale"}
    assert QuestionSet.model_validate(stale).version == saved.version
