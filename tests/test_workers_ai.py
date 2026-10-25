import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from jevtester.credentials import CLOUDFLARE_TOKEN_ENV, CredentialError, WranglerToken
from jevtester.normalize import ChoiceAnswer
from jevtester.providers import target_result
from jevtester.providers.workers_ai import WorkersAIProvider
from jevtester.schemas import DecideBody
from jevtester.service import Service, build_providers
from jevtester.spec import DecisionRequest, load_config

ROOT = Path(__file__).parent.parent
CONFIG = load_config(ROOT / "jevtester.toml")
TARGET = CONFIG.targets["clef-flash@workers-ai"]
ACCOUNT = "test-account"
"""A made-up account. The shared jevtester.toml leaves `cloudflare.account_id` unset."""
RUN_PATH = f"/client/v4/accounts/{ACCOUNT}/ai/run/@cf/cloudflare/clef-flash"
SEARCH_PATH = f"/client/v4/accounts/{ACCOUNT}/ai/models/search"

PLAN_REQUEST = json.loads((ROOT / "tests" / "fixtures" / "systemone" / "parley_request.json").read_text())
REQUEST = DecisionRequest.model_validate({"state": PLAN_REQUEST["state"], "questions": PLAN_REQUEST["questions"]})


def clef_result() -> dict[str, Any]:
    """A System One body rounded the way Clef-flash on Workers AI rounds, with output tokens at 0."""
    return {
        "model": "clef-flash",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "parley",
                "confidence": 0.9828,
                "probabilities": {"parley": 0.9871, "evade": 0.0042, "fight": 0.0019, "wait": 0.0068},
            },
            "bribe": {"type": "noul", "noul": 0.9912},
            "reaction": {
                "type": "score",
                "score": 2.1679,
                "confidence": 0.31,
                "legend": {str(i): text for i, text in enumerate(PLAN_REQUEST["questions"]["reaction"]["criteria"])},
                "probabilities": {"0": 0.0512, "1": 0.2143, "2": 0.4021, "3": 0.1802, "4": 0.1522},
            },
        },
        "usage": {"input_tokens": 185, "output_tokens": 0},
    }


def envelope(result: Any) -> dict[str, Any]:
    return {"result": result, "success": True, "errors": [], "messages": []}


class FakeToken:
    def __init__(self, fail: bool = False) -> None:
        self.issued = 0
        self.invalidated = 0
        self.fail = fail

    async def token(self) -> str:
        if self.fail:
            raise CredentialError("The Wrangler sign-in failed. Run npx wrangler login.")
        self.issued += 1
        return f"cf-{self.issued}"

    def describe(self) -> str | None:
        return "Wrangler sign-in"

    def invalidate(self) -> None:
        self.invalidated += 1


class Server:
    """Answers each request with the next response in a list, and records the requests."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        status, body = self.responses.pop(0)
        return httpx2.Response(status, json=body)


def provider(server: Server, token: FakeToken | None = None, account: str | None = ACCOUNT) -> WorkersAIProvider:
    return WorkersAIProvider(
        TARGET, account, token or FakeToken(), transport=httpx2.MockTransport(server), retry_delays=(0, 0)
    )


def test_decide_sends_the_system_one_body_and_unwraps_the_envelope() -> None:
    server = Server((200, envelope(clef_result())))
    raw = asyncio.run(provider(server).decide(REQUEST, timeout=5))

    sent = server.requests[0]
    assert sent.url.path == RUN_PATH
    assert sent.headers["authorization"] == "Bearer cf-1"
    assert json.loads(sent.content) == {**PLAN_REQUEST, "model": "clef-flash"}
    assert raw.error is None
    assert raw.warnings == []
    assert raw.response_body == envelope(clef_result())
    assert raw.system_one == clef_result()

    result = target_result(TARGET.name, REQUEST, raw, TARGET.capabilities)
    assert result.ok
    assert result.usage.output_tokens == 0
    assert result.cost_usd == pytest.approx(185 * 0.038 / 1_000_000)
    intent = result.answers["intent"]
    assert isinstance(intent, ChoiceAnswer)
    assert intent.choice == "parley"


def test_a_401_refreshes_the_token_once() -> None:
    token = FakeToken()
    server = Server(
        (401, {"success": False, "errors": [{"message": "Authentication error"}]}), (200, envelope(clef_result()))
    )
    raw = asyncio.run(provider(server, token).decide(REQUEST, timeout=5))
    assert raw.error is None
    assert token.invalidated == 1
    assert [request.headers["authorization"] for request in server.requests] == ["Bearer cf-1", "Bearer cf-2"]


def test_a_second_401_is_an_auth_error() -> None:
    rejected = (401, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
    raw = asyncio.run(provider(Server(rejected, rejected)).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert (raw.error.code, raw.error.status, raw.error.message) == ("auth", 401, "Authentication error")


def test_429_and_5xx_are_retried() -> None:
    server = Server((429, {}), (503, {}), (200, envelope(clef_result())))
    raw = asyncio.run(provider(server).decide(REQUEST, timeout=5))
    assert raw.error is None
    assert len(server.requests) == 3


def test_retries_stop_after_the_last_delay() -> None:
    server = Server((500, {}), (500, {}), (500, {"errors": [{"message": "Internal error"}]}))
    raw = asyncio.run(provider(server).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert (raw.error.code, raw.error.message) == ("server_error", "Internal error")


def test_an_envelope_without_a_result_is_an_invalid_response() -> None:
    raw = asyncio.run(provider(Server((200, {"success": True, "errors": []}))).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert raw.error.code == "invalid_response"


def test_a_result_the_sdk_rejects_has_a_warning() -> None:
    result = clef_result()
    del result["answers"]["intent"]["confidence"]
    raw = asyncio.run(provider(Server((200, envelope(result)))).decide(REQUEST, timeout=5))
    assert [warning.code for warning in raw.warnings] == ["strict_parse_failed"]
    assert raw.system_one == result


def test_no_account_is_not_ready() -> None:
    raw = asyncio.run(provider(Server(), account=None).decide(REQUEST, timeout=5))
    assert raw.error is not None
    assert raw.error.code == "not_ready"


def test_health_check_finds_the_model() -> None:
    search = (200, {"success": True, "result": [{"name": "@cf/cloudflare/clef-flash"}]})
    server = Server(search)
    health = asyncio.run(provider(server).health_check())
    assert health.reason is None
    assert health.credential == "Wrangler sign-in"
    assert server.requests[0].url.path == SEARCH_PATH
    assert server.requests[0].url.params["search"] == "clef-flash"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        ((200, {"success": True, "result": [{"name": "@cf/cloudflare/clef"}]}), "clef-flash isn't on Workers AI"),
        ((403, {"success": False}), "The token was rejected"),
    ],
)
def test_health_check_reports_problems(response: tuple[int, Any], reason: str) -> None:
    assert asyncio.run(provider(Server(response)).health_check()).reason == reason


def test_health_check_without_a_token() -> None:
    health = asyncio.run(provider(Server(), FakeToken(fail=True)).health_check())
    assert health.reason == "Can't get a token"
    assert health.detail is not None
    assert "wrangler login" in health.detail


def test_every_workers_target_gets_a_provider() -> None:
    providers = build_providers(CONFIG)
    for target in CONFIG.targets.values():
        if target.provider == "workers-ai":
            assert isinstance(providers[target.name], WorkersAIProvider)


# The Wrangler token


def test_wrangler_token_is_read_and_cached() -> None:
    calls: list[int] = []
    now = [0.0]

    async def run() -> tuple[int, bytes]:
        calls.append(1)
        return 0, json.dumps({"type": "oauth", "token": f"t{len(calls)}"}).encode()

    token = WranglerToken(run=run, environ={}, clock=lambda: now[0])
    assert token.describe() is None
    assert asyncio.run(token.token()) == "t1"
    assert asyncio.run(token.token()) == "t1"
    assert token.describe() == "Wrangler sign-in"
    now[0] = 601
    assert asyncio.run(token.token()) == "t2"
    token.invalidate()
    assert asyncio.run(token.token()) == "t3"


def test_the_environment_token_wins() -> None:
    async def run() -> tuple[int, bytes]:
        raise AssertionError("Wrangler shouldn't run")

    token = WranglerToken(run=run, environ={CLOUDFLARE_TOKEN_ENV: "from-env"})
    assert asyncio.run(token.token()) == "from-env"
    assert token.describe() == CLOUDFLARE_TOKEN_ENV


@pytest.mark.parametrize("output", [(1, b""), (0, b"not json"), (0, b'{"type": "oauth"}')])
def test_a_failed_wrangler_sign_in_raises(output: tuple[int, bytes]) -> None:
    async def run() -> tuple[int, bytes]:
        return output

    with pytest.raises(CredentialError, match="wrangler login"):
        asyncio.run(WranglerToken(run=run, environ={}).token())


def test_wrangler_that_cant_run_raises() -> None:
    async def run() -> tuple[int, bytes]:
        raise FileNotFoundError("npx")

    with pytest.raises(CredentialError, match="Install it"):
        asyncio.run(WranglerToken(run=run, environ={}).token())


# Live checks, run with `uv run pytest -m live` from the repository root. They read your jevtester.local.toml.


@pytest.mark.live
def test_live_workers_ai_decide() -> None:
    service = Service.load()
    body = DecideBody(state=REQUEST.state, questions=REQUEST.questions, targets=[TARGET.name])
    result = asyncio.run(service.decide(body)).results[0]
    assert result.ok, result.error
    assert result.usage.input_tokens
    assert [warning.code for warning in result.warnings] == ["state_may_truncate"]


@pytest.mark.live
def test_live_workers_ai_health_check() -> None:
    service = Service.load()
    targets = asyncio.run(service.check_targets())
    workers = [info for info in targets.targets if info.provider == "workers-ai"]
    assert [info.status for info in workers] == ["warning", "warning", "warning"], [info.reason for info in workers]
