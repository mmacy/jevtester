"""A fake decision provider, for tests and for building fixtures from the real service code."""

from collections.abc import Callable
from typing import Any

from jevtester.providers import Health, RawResult
from jevtester.spec import Capabilities, DecisionRequest, Target

type Responder = Callable[[DecisionRequest, dict[str, Any]], RawResult]


class FakeProvider:
    """Answers from a function instead of a server, and records each request."""

    def __init__(self, target: Target, respond: Responder | None = None, health: Health | None = None) -> None:
        self.target = target
        self.capabilities: Capabilities = target.capabilities
        self._respond = respond
        self._health = health or Health()
        self.requests: list[DecisionRequest] = []

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult:
        self.requests.append(request)
        body = request.system_one_body(self.target.model)
        if self._respond is None:
            raise AssertionError(f"{self.target.name} wasn't expected to get a request")
        return self._respond(request, body)

    async def health_check(self) -> Health:
        return self._health
