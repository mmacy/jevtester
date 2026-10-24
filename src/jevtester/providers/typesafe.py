"""The one module that uses the TypeSafe SDK.

The SDK is at 0.x, so a breaking release should change only this file. Every other module works with System One
request bodies as JSON and with [`RawResult`][jevtester.providers.base.RawResult].
"""

import json
import time
from typing import Any, cast

import httpx2
from typesafe_sdk import (
    AsyncTypeSafeClient,
    RetryPolicy,
    SystemOneResponse,
    TypeSafeAPIConnectionError,
    TypeSafeAPIError,
    TypeSafeAPIResponseValidationError,
    TypeSafeAPITimeoutError,
    TypeSafeError,
)

from jevtester.normalize import ErrorCode, ResultError, ResultWarning
from jevtester.providers.base import RawResult

NO_KEY = "none"
"""The key sent to servers without authentication. The SDK requires one."""

_BODY_FIELDS = {"model", "state", "questions"}


def make_client(
    base_url: str, api_key: str | None, *, transport: httpx2.AsyncBaseTransport | None = None
) -> AsyncTypeSafeClient:
    """Build an SDK client for one System One server.

    Args:
        base_url: The API root. The SDK appends `/v1/systemone`.
        api_key: The bearer token. `None` sends a placeholder, for servers without authentication.
        transport: An HTTP transport to use instead of the network, for tests.

    Returns:
        A client with compression off, since Foundry rejects zstd request bodies.
    """
    return AsyncTypeSafeClient(api_key=api_key or NO_KEY, base_url=base_url, compression=False, transport=transport)


def _status_code(status: int) -> ErrorCode:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status == 413:
        return "request_too_large"
    if status >= 500:
        return "server_error"
    return "bad_request"


def _decoded(content: bytes) -> Any:
    try:
        return json.loads(content)
    except ValueError:
        return content.decode(errors="replace")


async def system_one(client: AsyncTypeSafeClient, body: dict[str, Any], *, timeout: float) -> RawResult:
    """Send one System One request body through the SDK.

    The SDK validates the response strictly. When that fails, the response body is still used, with a
    `strict_parse_failed` warning, and the normalizer reads it.

    Args:
        client: The SDK client for the target's server.
        body: The System One request body, with `model`, `state`, `questions`, and any extra fields.
        timeout: Seconds to wait, including the SDK's retries on 429 and 5xx responses.

    Returns:
        The request and response bodies and the latency, or an error. It never raises for a failed request.
    """
    started = time.perf_counter()

    def elapsed_ms() -> float:
        return round((time.perf_counter() - started) * 1000, 1)

    extra = {key: value for key, value in body.items() if key not in _BODY_FIELDS}
    # The SDK's annotations for state and questions use a recursive alias that pyright can't resolve, so the call
    # goes through Any and its result is typed again here.
    sdk: Any = client
    try:
        response = cast(
            SystemOneResponse,
            await sdk.system_one(
                state=body["state"],
                questions=body["questions"],
                model=body["model"],
                extra_body=extra or None,
                timeout=timeout,
                retry=RetryPolicy(timeout=timeout),
            ),
        )
    except TypeSafeAPIResponseValidationError as error:
        response_body = error.body
        warning = ResultWarning(
            code="strict_parse_failed", message=f"The SDK couldn't parse {error.field_path or 'the response'}."
        )
        return RawResult(
            request_body=body,
            status=error.status,
            response_body=response_body,
            system_one=cast(dict[str, Any], response_body) if isinstance(response_body, dict) else None,
            latency_ms=elapsed_ms(),
            warnings=[warning],
        )
    except TypeSafeAPITimeoutError:
        error = ResultError(code="timeout", message=f"No response in {timeout:g} s.")
        return RawResult(request_body=body, latency_ms=elapsed_ms(), error=error)
    except TypeSafeAPIConnectionError as error:
        return RawResult(
            request_body=body, latency_ms=elapsed_ms(), error=ResultError(code="connection", message=str(error))
        )
    except TypeSafeAPIError as error:
        result_error = ResultError(code=_status_code(error.status), message=str(error), status=error.status)
        return RawResult(
            request_body=body,
            status=error.status,
            response_body=error.body,
            latency_ms=elapsed_ms(),
            error=result_error,
        )
    except TypeSafeError as error:
        return RawResult(request_body=body, error=ResultError(code="bad_request", message=str(error)))
    raw = response.raw_http_response
    response_body = _decoded(raw.content)
    return RawResult(
        request_body=_decoded(raw.request.content),
        status=raw.status_code,
        response_body=response_body,
        system_one=cast(dict[str, Any], response_body) if isinstance(response_body, dict) else None,
        latency_ms=elapsed_ms(),
    )
