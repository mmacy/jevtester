import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest
from azure.core.credentials import AccessToken

import api_fixtures
from fakes import FakeProvider
from jevtester import cli
from jevtester.credentials import AzureCliToken, CredentialError
from jevtester.normalize import ChoiceAnswer
from jevtester.providers import Health, RawResult
from jevtester.providers.systemone import SystemOneProvider
from jevtester.providers.typesafe import make_client, system_one
from jevtester.schemas import DecideBody, DecideResponse, TargetList
from jevtester.service import Service, UnknownTargetError, is_local
from jevtester.spec import ChoiceQuestion, DecisionRequest, NoulQuestion, Question, load_config

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "systemone"
CONFIG = load_config(ROOT / "jevtester.toml")
FOUNDRY = CONFIG.targets["decision-1@foundry"]
MLX = CONFIG.targets["clef-flash-4bit@mlx"]
OLLAMA = CONFIG.targets["clef-flash@ollama"]

PLAN_REQUEST = json.loads((FIXTURES / "parley_request.json").read_text())
FOUNDRY_RESPONSE = json.loads((FIXTURES / "parley_response_foundry.json").read_text())
REQUEST = DecisionRequest.model_validate({"state": PLAN_REQUEST["state"], "questions": PLAN_REQUEST["questions"]})


class FakeCredential:
    def __init__(self, expires_on: int = 10_000, fail: bool = False) -> None:
        self.calls = 0
        self.expires_on = expires_on
        self.fail = fail

    async def get_token(self, *scopes: str) -> AccessToken:
        self.calls += 1
        if self.fail:
            raise RuntimeError("Please run 'az login' to set up an account.")
        return AccessToken(f"token-{self.calls}", self.expires_on)


class Recorder:
    """An HTTP handler that records requests and answers with one response."""

    def __init__(self, status: int = 200, body: Any = None, error: Exception | None = None) -> None:
        self.status = status
        self.body = FOUNDRY_RESPONSE if body is None else body
        self.error = error
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return httpx2.Response(self.status, json=self.body)


def provider_with(recorder: Recorder, target: Any = FOUNDRY, credential: Any = None) -> SystemOneProvider:
    return SystemOneProvider(target, credential, transport=httpx2.MockTransport(recorder))


# The SDK wrapper and the provider


def test_provider_sends_the_plan_request_with_the_token() -> None:
    recorder = Recorder()
    token = AzureCliToken(credential=FakeCredential(), clock=lambda: 0)
    raw = asyncio.run(provider_with(recorder, credential=token).decide(REQUEST, timeout=5))

    assert raw.error is None
    sent = recorder.requests[0]
    assert str(sent.url) == "https://example-resource.services.ai.azure.com/providers/microsoft/v1/systemone"
    assert sent.headers["authorization"] == "Bearer token-1"
    assert "content-encoding" not in sent.headers
    assert json.loads(sent.content) == PLAN_REQUEST
    assert raw.request_body == PLAN_REQUEST
    assert raw.system_one == FOUNDRY_RESPONSE
    assert raw.status == 200
    assert raw.latency_ms is not None


def test_provider_sends_truncate_when_the_target_sets_it() -> None:
    recorder = Recorder()
    asyncio.run(provider_with(recorder, target=MLX).decide(REQUEST, timeout=5))
    body = json.loads(recorder.requests[0].content)
    assert body["truncate"] is False
    assert body["model"] == "clef-flash-4bit"
    assert recorder.requests[0].headers["authorization"] == "Bearer none"


@pytest.mark.parametrize(
    ("status", "code"), [(400, "bad_request"), (401, "auth"), (403, "auth"), (413, "request_too_large")]
)
def test_http_errors_map_to_error_codes(status: int, code: str) -> None:
    recorder = Recorder(status=status, body={"error": {"message": "no"}})
    raw = asyncio.run(provider_with(recorder).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert (raw.error.code, raw.error.status) == (code, status)
    assert raw.response_body == {"error": {"message": "no"}}
    assert raw.system_one is None


def test_a_connection_error_is_reported() -> None:
    recorder = Recorder(error=httpx2.ConnectError("refused"))
    target = OLLAMA.model_copy(update={"base_url": "http://127.0.0.1:9"})
    client = make_client(target.base_url or "", None, transport=httpx2.MockTransport(recorder))
    raw = asyncio.run(system_one(client, REQUEST.system_one_body("m"), timeout=0.5))
    assert raw.error is not None
    assert raw.error.code == "connection"


def test_a_strict_parse_failure_still_yields_answers() -> None:
    body = json.loads(json.dumps(FOUNDRY_RESPONSE))
    del body["answers"]["intent"]["confidence"]
    raw = asyncio.run(provider_with(Recorder(body=body)).decide(REQUEST, timeout=5))
    assert raw.error is None
    assert [warning.code for warning in raw.warnings] == ["strict_parse_failed"]
    assert raw.system_one == body


def test_images_are_rejected_before_sending() -> None:
    recorder = Recorder()
    request = REQUEST.model_copy(update={"images": ["goblins.png"]})
    raw = asyncio.run(provider_with(recorder).decide(request, timeout=5))
    assert raw.error is not None
    assert raw.error.code == "preflight"
    assert recorder.requests == []


def test_a_failed_sign_in_is_an_auth_error() -> None:
    token = AzureCliToken(credential=FakeCredential(fail=True), clock=lambda: 0)
    raw = asyncio.run(provider_with(Recorder(), credential=token).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert raw.error.code == "auth"
    assert "az login" in raw.error.message


def test_health_check_reports_the_credential() -> None:
    token = AzureCliToken(credential=FakeCredential(expires_on=3000), clock=lambda: 0)
    health = asyncio.run(provider_with(Recorder(), credential=token).health_check())
    assert health == Health(credential="Azure CLI, refreshes in 45 min")

    failing = AzureCliToken(credential=FakeCredential(fail=True), clock=lambda: 0)
    health = asyncio.run(provider_with(Recorder(), credential=failing).health_check())
    assert health.reason == "Can't get a token"


def test_health_check_reports_a_server_that_isnt_listening() -> None:
    down = provider_with(Recorder(error=httpx2.ConnectError("refused")), target=OLLAMA)
    health = asyncio.run(down.health_check())
    assert health.reason == "The server isn't running"
    assert asyncio.run(provider_with(Recorder(), target=OLLAMA).health_check()) == Health()


# Tokens


def test_token_is_cached_until_near_expiry() -> None:
    now = [0.0]
    credential = FakeCredential(expires_on=3600)
    token = AzureCliToken(credential=credential, clock=lambda: now[0])
    assert token.describe() is None
    assert asyncio.run(token.token()) == "token-1"
    now[0] = 3000
    assert asyncio.run(token.token()) == "token-1"
    now[0] = 3301
    credential.expires_on = 7200
    assert asyncio.run(token.token()) == "token-2"
    assert credential.calls == 2


def test_token_failure_raises_a_credential_error() -> None:
    token = AzureCliToken(credential=FakeCredential(fail=True))
    with pytest.raises(CredentialError, match="az login"):
        asyncio.run(token.token())


# The service


def respond_ok(request: DecisionRequest, body: dict[str, Any]) -> RawResult:
    return RawResult(request_body=body, status=200, response_body=FOUNDRY_RESPONSE, system_one=FOUNDRY_RESPONSE)


def service_with(**providers: FakeProvider) -> Service:
    return Service(CONFIG, {provider.target.name: provider for provider in providers.values()})


def test_decide_uses_the_default_targets() -> None:
    foundry = FakeProvider(FOUNDRY, respond_ok)
    response = asyncio.run(service_with(foundry=foundry).decide(DecideBody(state="s", questions=REQUEST.questions)))
    assert [result.target for result in response.results] == ["decision-1@foundry"]
    assert response.results[0].ok
    assert response.question_set_version == api_fixtures.QUESTION_SET.version
    assert isinstance(response.results[0].answers["intent"], ChoiceAnswer)


def test_decide_keeps_the_order_named_and_reports_each_failure() -> None:
    service = service_with(foundry=FakeProvider(FOUNDRY, respond_ok))
    body = DecideBody(state="s", questions=REQUEST.questions, targets=["clef-flash@workers-ai", "decision-1@foundry"])
    response = asyncio.run(service.decide(body))
    assert [result.target for result in response.results] == ["clef-flash@workers-ai", "decision-1@foundry"]
    workers = response.results[0]
    assert not workers.ok
    assert workers.error is not None
    assert workers.error.code == "not_ready"


def test_decide_skips_a_target_whose_last_check_failed() -> None:
    ollama = FakeProvider(OLLAMA, respond_ok, Health(reason="clef-flash isn't pulled"))
    service = service_with(ollama=ollama)
    asyncio.run(service.check_targets())
    response = asyncio.run(service.decide(DecideBody(state="s", questions=REQUEST.questions, targets=[OLLAMA.name])))
    error = response.results[0].error
    assert error is not None
    assert (error.code, error.message) == ("not_ready", "clef-flash isn't pulled")
    assert ollama.requests == []


def test_decide_rejects_in_preflight_without_sending() -> None:
    ollama = FakeProvider(OLLAMA, respond_ok)
    options = {f"option{i}": f"Option {i}" for i in range(27)}
    questions: dict[str, Question] = {"q": ChoiceQuestion(instructions="?", criteria=options)}
    response = asyncio.run(
        service_with(ollama=ollama).decide(DecideBody(state="s", questions=questions, targets=[OLLAMA.name]))
    )
    error = response.results[0].error
    assert error is not None
    assert error.code == "preflight"
    assert "27 options" in error.message
    assert ollama.requests == []


def test_decide_rejects_an_unknown_target() -> None:
    with pytest.raises(UnknownTargetError) as raised:
        asyncio.run(service_with().decide(DecideBody(state="s", questions=REQUEST.questions, targets=["x@y"])))
    assert raised.value.field == "targets.0"


def test_decide_all_sends_to_every_target() -> None:
    assert len(service_with().resolve_targets(["all"])) == len(CONFIG.targets)


def test_workers_results_carry_the_truncation_warning() -> None:
    workers = CONFIG.targets["clef-flash@workers-ai"]
    service = service_with(workers=FakeProvider(workers, respond_ok))
    body = DecideBody(state="s", questions=REQUEST.questions, targets=[workers.name])
    result = asyncio.run(service.decide(body)).results[0]
    assert [warning.code for warning in result.warnings][:1] == ["state_may_truncate"]


def test_target_status_follows_the_health_check() -> None:
    service = service_with(
        foundry=FakeProvider(FOUNDRY, health=Health(credential="Azure CLI, refreshes in 41 min")),
        ollama=FakeProvider(OLLAMA, health=Health(reason="clef-flash isn't pulled")),
        workers=FakeProvider(CONFIG.targets["clef-flash@workers-ai"]),
    )
    before = {info.name: info.status for info in service.list_targets().targets}
    assert set(before.values()) == {"unchecked"}
    after = {info.name: info for info in asyncio.run(service.check_targets()).targets}
    assert after["decision-1@foundry"].status == "ready"
    assert after["decision-1@foundry"].credential == "Azure CLI, refreshes in 41 min"
    assert after["clef-flash@ollama"].status == "down"
    assert after["clef-flash@workers-ai"].status == "warning"
    assert after["clef@workers-ai"].reason == "The workers-ai provider isn't built yet"


def test_local_targets() -> None:
    assert is_local(OLLAMA)
    assert is_local(MLX)
    assert not is_local(FOUNDRY)


# The CLI


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> Service:
    service = service_with(foundry=FakeProvider(FOUNDRY, respond_ok))
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    return service


def test_cli_quick_test_is_a_noul_question(fake_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["decide", "--state", "Six goblins.", "--question", "Hostile?", "--format", "json"])
    assert code == 0
    response = DecideResponse.model_validate_json(capsys.readouterr().out)
    assert response.request.questions == {"question": NoulQuestion(instructions="Hostile?")}


def test_cli_options_make_a_choice(fake_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["decide", "--state", "s", "--question", "What?", "--id", "intent", "--option", "parley=Talk"]
    code = cli.main([*args, "--option", "fight=Attack", "--format", "json"])
    assert code == 0
    question = DecideResponse.model_validate_json(capsys.readouterr().out).request.questions["intent"]
    assert question == ChoiceQuestion(instructions="What?", criteria={"parley": "Talk", "fight": "Attack"})


def test_cli_reads_a_request_file(fake_service: Service, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(PLAN_REQUEST))
    assert cli.main(["decide", "--request", str(path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("decision-1@foundry")
    assert "intent: parley" in out


def test_cli_reads_a_json_state_file(fake_service: Service, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps(PLAN_REQUEST["state"]))
    assert cli.main(["decide", "--state", f"@{path}", "--question", "Bribe?", "--format", "json"]) == 0
    assert DecideResponse.model_validate_json(capsys.readouterr().out).request.state == PLAN_REQUEST["state"]


@pytest.mark.parametrize(
    "args",
    [
        ["decide", "--question", "No state?"],
        ["decide", "--state", "s", "--question", "?", "--option", "nameless"],
        ["decide", "--state", "s", "--question", "?", "--option", "a=A", "--level", "low"],
        ["decide", "--state", "s", "--question", "?", "--option", "only=One"],
        ["decide", "--state", "s", "--question", "?", "--target", "x@y"],
    ],
)
def test_cli_invalid_input_exits_with_2(fake_service: Service, args: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(args)
    assert exit_info.value.code == 2


def test_cli_exits_with_3_when_every_target_fails(fake_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["decide", "--state", "s", "--question", "?", "--target", "clef-flash@workers-ai"])
    assert code == 3
    assert "failed  not_ready" in capsys.readouterr().out


def test_cli_targets_list_and_check(fake_service: Service, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["targets", "list", "--format", "json"]) == 0
    listed = TargetList.model_validate_json(capsys.readouterr().out)
    assert listed.default_targets == ["decision-1@foundry"]
    assert cli.main(["targets", "check"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:2] == ["decision-1@foundry", "ready"]


# Live checks, run with `uv run pytest -m live`


@pytest.mark.live
def test_live_foundry_decide() -> None:
    service = Service.load(ROOT / "jevtester.toml")
    response = asyncio.run(service.decide(DecideBody(state=REQUEST.state, questions=REQUEST.questions)))
    result = response.results[0]
    assert result.ok, result.error
    intent = result.answers["intent"]
    assert isinstance(intent, ChoiceAnswer)
    assert intent.choice == "parley"
    assert result.warnings == []


@pytest.mark.live
def test_live_foundry_health_check() -> None:
    service = Service.load(ROOT / "jevtester.toml")
    targets = asyncio.run(service.check_targets())
    foundry = next(info for info in targets.targets if info.name == "decision-1@foundry")
    assert foundry.status == "ready", foundry.reason
    assert foundry.credential is not None
