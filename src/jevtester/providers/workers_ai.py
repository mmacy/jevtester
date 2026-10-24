"""The provider for Clef models on Cloudflare Workers AI.

Workers AI takes the System One body unchanged and wraps the System One response in a Cloudflare envelope:
`{"result": {...}, "success": true, "errors": [], "messages": []}`.
"""

import asyncio
import time
from collections.abc import Sequence
from typing import Any, cast

import httpx2

from jevtester.credentials import CredentialError, TokenSource
from jevtester.normalize import ResultError, ResultWarning
from jevtester.providers.base import Health, RawResult
from jevtester.providers.typesafe import decoded, error_code, strict_parse_warning
from jevtester.spec import Capabilities, DecisionRequest, Target

CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
MODEL_PREFIX = "@cf/cloudflare/"
RETRY_DELAYS_S = (0.5, 1.0)
"""Waits before each retry of a 429 or 5xx response."""
HEALTH_TIMEOUT_S = 15.0


def _is_retryable(status: int) -> bool:
    return status == 429 or status >= 500


class WorkersAIProvider:
    """A Clef model on Workers AI, called over HTTP."""

    def __init__(
        self,
        target: Target,
        account_id: str | None,
        credential: TokenSource,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        retry_delays: Sequence[float] = RETRY_DELAYS_S,
    ) -> None:
        """Connect to one Workers AI model.

        Args:
            target: The target. Its `model` is the name after `@cf/cloudflare/`.
            account_id: The Cloudflare account. `None` leaves the target not ready.
            credential: Where the bearer token comes from.
            transport: An HTTP transport to use instead of the network, for tests.
            retry_delays: Seconds to wait before each retry of a 429 or 5xx response.
        """
        self.target = target
        self.capabilities: Capabilities = target.capabilities
        self._account_id = account_id
        self._credential = credential
        self._transport = transport
        self._retry_delays = tuple(retry_delays)
        self._client: httpx2.AsyncClient | None = None

    def _http(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(transport=self._transport)
        return self._client

    def _account_url(self, path: str) -> str:
        return f"{CLOUDFLARE_API}/accounts/{self._account_id}/{path}"

    async def decide(self, request: DecisionRequest, *, timeout: float) -> RawResult:
        """Send one request, refreshing the token once on a 401 and retrying 429 and 5xx responses.

        Args:
            request: The state and questions to send.
            timeout: Seconds to wait, including retries.

        Returns:
            The request body, the whole Cloudflare envelope as the response body, the System One `result` inside it,
            and the latency, or an error.
        """
        if request.images:
            error = ResultError(code="preflight", message="Images aren't supported on Workers AI targets yet.")
            return RawResult(request_body=None, error=error)
        if self._account_id is None:
            return RawResult(request_body=None, error=ResultError(code="not_ready", message="No Cloudflare account"))
        body = request.system_one_body(self.target.model)
        url = self._account_url(f"ai/run/{MODEL_PREFIX}{self.target.model}")
        started = time.perf_counter()
        deadline = started + timeout

        def elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 1)

        refreshed = False
        retries = iter(self._retry_delays)
        while True:
            try:
                token = await self._credential.token()
            except CredentialError as error:
                return RawResult(request_body=None, error=ResultError(code="auth", message=str(error)))
            remaining = deadline - time.perf_counter()
            try:
                response = await self._http().post(
                    url, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=max(remaining, 0.1)
                )
            except httpx2.TimeoutException:
                error = ResultError(code="timeout", message=f"No response in {timeout:g} s.")
                return RawResult(request_body=body, latency_ms=elapsed_ms(), error=error)
            except httpx2.HTTPError as error:
                result_error = ResultError(code="connection", message=f"Connection error: {error}")
                return RawResult(request_body=body, latency_ms=elapsed_ms(), error=result_error)
            if response.status_code == 401 and not refreshed:
                self._credential.invalidate()
                refreshed = True
                continue
            if _is_retryable(response.status_code):
                delay = next(retries, None)
                if delay is not None and time.perf_counter() + delay < deadline:
                    await asyncio.sleep(delay)
                    continue
            break
        return self._result(body, response, elapsed_ms())

    def _result(self, body: dict[str, Any], response: httpx2.Response, latency_ms: float) -> RawResult:
        envelope = decoded(response.content)
        status = response.status_code
        if status >= 400:
            message = _envelope_errors(envelope) or f"Workers AI returned {status}."
            error = ResultError(code=error_code(status), message=message, status=status)
            return RawResult(
                request_body=body, status=status, response_body=envelope, latency_ms=latency_ms, error=error
            )
        result = _get(envelope, "result")
        if not isinstance(result, dict):
            error = ResultError(code="invalid_response", message="The response has no result.", status=status)
            return RawResult(
                request_body=body, status=status, response_body=envelope, latency_ms=latency_ms, error=error
            )
        system_one = cast(dict[str, Any], result)
        warning = strict_parse_warning(system_one)
        warnings: list[ResultWarning] = [warning] if warning else []
        return RawResult(
            request_body=body,
            status=status,
            response_body=envelope,
            system_one=system_one,
            latency_ms=latency_ms,
            warnings=warnings,
        )

    async def health_check(self) -> Health:
        """Check that a token can be read and that Workers AI lists the model.

        Returns:
            Ready when the model is in the account's Workers AI catalog, with the credential's source.
        """
        if self._account_id is None:
            return Health(reason="No Cloudflare account", detail="Set cloudflare.account_id in jevtester.toml")
        try:
            token = await self._credential.token()
        except CredentialError as error:
            return Health(reason="Can't get a token", detail=str(error))
        try:
            response = await self._http().get(
                self._account_url("ai/models/search"),
                params={"search": self.target.model},
                headers={"Authorization": f"Bearer {token}"},
                timeout=HEALTH_TIMEOUT_S,
            )
        except httpx2.HTTPError as error:
            return Health(reason="Can't reach Workers AI", detail=str(error))
        if response.status_code in (401, 403):
            self._credential.invalidate()
            return Health(reason="The token was rejected", detail="Run npx wrangler login")
        envelope = decoded(response.content)
        models = _get(envelope, "result")
        names = {
            cast(dict[str, Any], model).get("name")
            for model in cast(list[Any], models or [])
            if isinstance(model, dict)
        }
        if f"{MODEL_PREFIX}{self.target.model}" not in names:
            return Health(reason=f"{self.target.model} isn't on Workers AI", detail=f"Searched for {self.target.model}")
        return Health(credential=self._credential.describe())


def _get(value: Any, key: str) -> Any:
    return cast(dict[str, Any], value).get(key) if isinstance(value, dict) else None


def _envelope_errors(envelope: Any) -> str | None:
    errors = _get(envelope, "errors")
    if not isinstance(errors, list):
        return None
    messages = [
        str(cast(dict[str, Any], error).get("message")) for error in cast(list[Any], errors) if isinstance(error, dict)
    ]
    return "; ".join(messages) or None
