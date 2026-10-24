"""One request to one target: preflight, the call, and normalization."""

import asyncio
import hashlib
import json

from jevtester.normalize import ResultError, ResultWarning, TargetResult
from jevtester.preflight import preflight, target_warnings
from jevtester.providers import DecisionProvider, RawResult, target_result
from jevtester.spec import DecisionRequest, Target

TIMEOUT_GRACE_S = 5.0
"""Extra seconds before jevtester gives up on a provider that doesn't honor its own timeout."""


def not_sent(target: Target, error: ResultError, warnings: list[ResultWarning] | None = None) -> TargetResult:
    """Build the result for a request that wasn't sent.

    Args:
        target: The target.
        error: Why it wasn't sent.
        warnings: Warnings found before it was stopped.

    Returns:
        A result with `ok: false` and no request body.
    """
    return TargetResult(target=target.name, ok=False, error=error, warnings=warnings or [])


async def ask(target: Target, provider: DecisionProvider, request: DecisionRequest, timeout: float) -> TargetResult:
    """Check a request against the target's limits, send it, and normalize the answer.

    Args:
        target: The target.
        provider: The target's provider.
        request: The state and questions.
        timeout: Seconds to wait for the provider.

    Returns:
        The result, with preflight warnings first, then the target's own warnings, then the provider's.
    """
    error, warnings = preflight(request, target)
    if error is not None:
        return not_sent(target, error, warnings)
    try:
        raw = await asyncio.wait_for(provider.decide(request, timeout=timeout), timeout + TIMEOUT_GRACE_S)
    except TimeoutError:
        raw = RawResult(request_body=None, error=ResultError(code="timeout", message=f"No response in {timeout:g} s."))
    result = target_result(target.name, request, raw, target.capabilities)
    codes = {warning.code for warning in warnings}
    result.warnings = [
        *warnings,
        *(warning for warning in target_warnings(target) if warning.code not in codes),
        *result.warnings,
    ]
    return result


def cache_key(target: Target, request: DecisionRequest, repeat: int) -> str:
    """Hash a job so an unchanged rerun can reuse its result.

    Args:
        target: The target.
        request: The state and questions.
        repeat: The repeat index. Repeats measure consistency, so each repeat is its own job.

    Returns:
        A SHA-256 hex digest over the target's name and model, its `truncate` setting, the request, and the repeat.
    """
    key = {
        "target": target.name,
        "body": request.system_one_body(target.model),
        "truncate": target.truncate,
        "images": request.images,
        "repeat": repeat,
    }
    return hashlib.sha256(json.dumps(key, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
