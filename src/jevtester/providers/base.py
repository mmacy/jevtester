"""The protocol every decision provider implements, and what a provider returns."""

from typing import Any, Protocol

from pydantic import Field, JsonValue

from jevtester.model import Model
from jevtester.normalize import (
    InvalidResponseError,
    ResultError,
    ResultWarning,
    TargetResult,
    cost_usd,
    normalize,
    normalize_usage,
)
from jevtester.spec import Capabilities, DecisionRequest


class RawResult(Model):
    """What a provider got back from one request, before normalization."""

    request_body: JsonValue
    """The exact body sent to the server."""
    status: int | None = None
    """The HTTP status. `None` when no response arrived."""
    response_body: JsonValue = None
    """The server's response body, unchanged."""
    system_one: dict[str, Any] | None = None
    """The System One response inside `response_body`. For Workers AI it's the envelope's `result`. `None` on error."""
    latency_ms: float | None = None
    error: ResultError | None = None
    """Why no answers came back. `None` when `system_one` is set."""
    warnings: list[ResultWarning] = Field(default_factory=list[ResultWarning])
    """Warnings the provider found, like a strict SDK parse that failed."""


class Health(Model):
    """A target's health check result."""

    reason: str | None = None
    """Why the target isn't ready, like `Ollama isn't running`. `None` when it's ready."""
    detail: str | None = None
    """More about the reason or the target's state, like `Needs 0.35.1 or later`."""
    credential: str | None = None
    """Where the credential comes from and when it expires, like `Azure CLI, refreshes in 41 min`."""


class DecisionProvider(Protocol):
    """One target's connection to a decision model.

    A provider never raises for a failed request. It returns a [`RawResult`][jevtester.providers.base.RawResult]
    with an `error`, so the runner records every failure the same way.
    """

    capabilities: Capabilities

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult:
        """Send one request and return the server's response.

        Args:
            request: The state and questions to send.
            timeout: Seconds to wait for the response, including retries.

        Returns:
            The request and response bodies, the latency, and an error if no answers came back.
        """
        ...

    async def health_check(self) -> Health:
        """Check whether the target can take requests now.

        Returns:
            A [`Health`][jevtester.providers.base.Health] whose `reason` is `None` when the target is ready.
        """
        ...


def target_result(target: str, request: DecisionRequest, raw: RawResult, capabilities: Capabilities) -> TargetResult:
    """Normalize a provider's raw result into a [`TargetResult`][jevtester.normalize.TargetResult].

    Args:
        target: The target's name.
        request: The request that was sent.
        raw: What the provider got back.
        capabilities: The target's capabilities, for the cost.

    Returns:
        The canonical result. A response with no `answers` object becomes an `invalid_response` error.
    """
    base = TargetResult(
        target=target,
        ok=False,
        latency_ms=raw.latency_ms,
        warnings=list(raw.warnings),
        error=raw.error,
        request_body=raw.request_body,
        raw=raw.response_body,
    )
    if raw.error is not None or raw.system_one is None:
        if base.error is None:
            base.error = ResultError(code="invalid_response", message="The response has no System One body.")
        return base
    usage = normalize_usage(raw.system_one)
    base.usage = usage
    base.cost_usd = cost_usd(usage, capabilities)
    try:
        answers, warnings = normalize(request.questions, raw.system_one)
    except InvalidResponseError as error:
        base.error = ResultError(code="invalid_response", message=str(error), status=raw.status)
        return base
    base.ok = True
    base.answers = answers
    base.warnings.extend(warnings)
    return base
