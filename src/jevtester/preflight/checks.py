"""Check a request against a target's capabilities before sending it."""

import json
from pathlib import Path

from jevtester.normalize import ResultError, ResultWarning
from jevtester.spec import ChoiceQuestion, DecisionRequest, ImageFormat, NoulQuestion, ScoreQuestion, Target

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


def image_format(header: bytes) -> ImageFormat | None:
    """Recognize an image format from a file's first bytes.

    Args:
        header: At least the file's first 12 bytes.

    Returns:
        `png`, `jpeg`, or `webp`, or `None` for any other format.
    """
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    return None


def _check_images(images: list[str], target: Target) -> str | None:
    # Reads each image file, at its path as given, only when the target limits image size or format.
    capabilities = target.capabilities
    formats = capabilities.image_formats
    if capabilities.max_image_bytes is None and capabilities.max_total_image_bytes is None and not formats:
        return None
    total = 0
    for image in images:
        path = Path(image)
        try:
            size = path.stat().st_size
            with path.open("rb") as file:
                header = file.read(12)
        except OSError as error:
            return f"Can't read {image}: {error.strerror or error}."
        if formats:
            found = image_format(header)
            if found not in formats:
                return f"{image} is {found or 'an unknown format'}. {target.name} accepts {_join(formats)}."
        if capabilities.max_image_bytes is not None and size > capabilities.max_image_bytes:
            return f"{image} is {size:,} bytes, over the limit of {capabilities.max_image_bytes:,}."
        total += size
    if capabilities.max_total_image_bytes is not None and total > capabilities.max_total_image_bytes:
        return f"The images total {total:,} bytes, over the limit of {capabilities.max_total_image_bytes:,}."
    return None


def _join(words: list[ImageFormat]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


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
        problem = _check_images(request.images, target)
        if problem is not None:
            return reject(problem)

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
