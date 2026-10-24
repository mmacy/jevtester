"""Check a request against a target's capabilities before sending it."""

import json

from jevtester.normalize import ResultError, ResultWarning
from jevtester.spec import ChoiceQuestion, DecisionRequest, NoulQuestion, ScoreQuestion, Target

BYTES_PER_TOKEN = 4
"""A rough token estimate for English text and JSON. Preflight rejects only when the estimate is far over a limit."""
REJECT_FACTOR = 1.25
"""Reject a request only when its estimate is this far over a context window that doesn't truncate."""


def estimate_tokens(body: dict[str, object]) -> int:
    """Estimate a request body's input tokens from its JSON size.

    Args:
        body: The System One request body.

    Returns:
        The estimated token count.
    """
    return len(json.dumps(body, ensure_ascii=False).encode()) // BYTES_PER_TOKEN


def preflight(request: DecisionRequest, target: Target) -> tuple[ResultError | None, list[ResultWarning]]:
    """Check a request against a target's limits.

    Args:
        request: The request to send.
        target: The target to send it to.

    Returns:
        A `preflight` error when the request would fail, so it isn't sent, and warnings for anything that would
        change the answer without an error, like silent truncation.
    """
    capabilities = target.capabilities
    warnings: list[ResultWarning] = []

    def reject(message: str) -> tuple[ResultError, list[ResultWarning]]:
        return ResultError(code="preflight", message=message), warnings

    unsupported = sorted({q.type for q in request.questions.values()} - set(capabilities.question_types))
    if unsupported:
        return reject(f"{target.name} doesn't accept {', '.join(unsupported)} questions.")
    if capabilities.max_questions is not None and len(request.questions) > capabilities.max_questions:
        return reject(f"{len(request.questions)} questions, over the limit of {capabilities.max_questions}.")
    for key, question in request.questions.items():
        match question:
            case NoulQuestion():
                continue
            case ChoiceQuestion():
                count = len(question.criteria)
            case ScoreQuestion():
                count = len(question.criteria)
        if capabilities.min_options is not None and count < capabilities.min_options:
            return reject(f"{key} has {count} options, under the minimum of {capabilities.min_options}.")
        if capabilities.max_options is not None and count > capabilities.max_options:
            return reject(f"{key} has {count} options, over the limit of {capabilities.max_options}.")
    if request.images:
        if not capabilities.images:
            return reject(f"{target.name} doesn't accept images.")
        if capabilities.max_images is not None and len(request.images) > capabilities.max_images:
            return reject(f"{len(request.images)} images, over the limit of {capabilities.max_images}.")

    body = request.system_one_body(target.model)
    size = len(json.dumps(body, ensure_ascii=False).encode())
    if capabilities.max_request_bytes is not None and size > capabilities.max_request_bytes:
        return reject(f"The request is {size:,} bytes, over the limit of {capabilities.max_request_bytes:,}.")
    window = capabilities.context_window
    tokens = estimate_tokens(body)
    if window is not None and tokens > window:
        if capabilities.truncates_state or target.truncate:
            warnings.append(
                ResultWarning(
                    code="state_may_truncate",
                    message=f"About {tokens:,} tokens, over the {window:,}-token window. The server cuts the state.",
                )
            )
        elif tokens > window * REJECT_FACTOR:
            return reject(f"About {tokens:,} tokens, over the {window:,}-token window.")
    return None, warnings


def target_warnings(target: Target) -> list[ResultWarning]:
    """List the warnings that apply to every request a target gets.

    Args:
        target: The target.

    Returns:
        `state_may_truncate` for a server that truncates the state, and `truncation_on` for a target configured to
        truncate.
    """
    warnings: list[ResultWarning] = []
    if target.capabilities.truncates_state:
        window = target.capabilities.context_window
        limit = f"its {window:,}-token window" if window else "its context window"
        warnings.append(ResultWarning(code="state_may_truncate", message=f"Cuts the state to fit {limit}"))
    if target.truncate:
        warnings.append(ResultWarning(code="truncation_on", message="Truncation on"))
    return warnings
