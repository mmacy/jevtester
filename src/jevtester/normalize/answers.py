"""Canonical answers and the result of one request to one target.

Every target's response maps to these types, so the runner, the evaluator, the CLI, and the API compare targets on
the same fields.
"""

from typing import Annotated, Literal

from pydantic import Field, JsonValue

from jevtester.model import Model


class NoulAnswer(Model):
    """The answer to a yes/no question."""

    type: Literal["noul"] = "noul"
    probability: float
    """The probability of yes."""
    confidence: float
    """`|2p - 1|`, computed by jevtester."""
    server_confidence: float | None = None
    """The server's confidence, when it sends one."""


class ChoiceAnswer(Model):
    """The answer to a choice question."""

    type: Literal["choice"] = "choice"
    choice: str
    """The option the server chose."""
    probabilities: dict[str, float]
    """The probability of each option, in the question's option order. An option the server sent no probability
    for is left out, with a `missing_probability` warning."""
    unknown_probabilities: dict[str, float] = Field(default_factory=dict[str, float])
    """Probabilities the server sent for options the question doesn't have, with an `unknown_option` warning."""
    confidence: float
    """`(p_max - 1/n) / (1 - 1/n)` over the question's `n` options, computed by jevtester."""
    server_confidence: float | None = None
    """The server's confidence, when it sends one."""


class ScoreAnswer(Model):
    """The answer to a score question."""

    type: Literal["score"] = "score"
    score: float
    """The probability-weighted level index. It can fall between levels."""
    level: int | None
    """The most probable level, and the lowest of any tied. Evaluation compares this level with the expected one.
    `None` when the server sent no level probabilities."""
    probabilities: list[float | None]
    """The probability of each level, lowest first. `None` for a level the server sent no probability for, with a
    `missing_probability` warning."""
    legend: list[str]
    """The question's level descriptions, lowest first."""
    confidence: float | None = None
    """Always `None`: jevtester uses the server's value for scores, since the formula isn't published."""
    server_confidence: float | None = None
    """The server's confidence."""


type Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]
"""A canonical answer, told apart by its `type`."""


class Usage(Model):
    """Token counts the server reports. `None` where it reports none."""

    input_tokens: int | None = None
    """Input tokens the server counted. `None` when it reports none."""
    output_tokens: int | None = None
    """Output tokens the server counted. `None` when it reports none."""


type WarningCode = Literal[
    "missing_answer",
    "invalid_answer",
    "unknown_option",
    "missing_probability",
    "unexpected_answer",
    "strict_parse_failed",
    "truncation_on",
    "state_may_truncate",
]
"""Why a result has a warning. A warning doesn't stop the result from counting."""


class ResultWarning(Model):
    """Something about a result that a person should know."""

    code: WarningCode
    """Why the result has a warning: `missing_answer`, `invalid_answer`, `unknown_option`, `missing_probability`,
    `unexpected_answer`, `strict_parse_failed`, `truncation_on`, or `state_may_truncate`."""
    message: str
    """What the warning is about, for a person."""
    question: str | None = None
    """The question id the warning is about, if it's about one."""


type ErrorCode = Literal[
    "not_ready",
    "preflight",
    "auth",
    "rate_limited",
    "bad_request",
    "request_too_large",
    "server_error",
    "timeout",
    "connection",
    "invalid_response",
]
"""Why a target returned no answers."""


class ResultError(Model):
    """Why a target returned no answers."""

    code: ErrorCode
    """Why the target returned no answers: `not_ready`, `preflight`, `auth`, `rate_limited`, `bad_request`,
    `request_too_large`, `server_error`, `timeout`, `connection`, or `invalid_response`."""
    message: str
    """What went wrong, for a person."""
    status: int | None = None
    """The HTTP status, when the server sent one."""


class TargetResult(Model):
    """The result of one request to one target."""

    target: str
    """The target's name."""
    ok: bool
    """`True` when the target answered. Some answers may still be missing; see `warnings`."""
    latency_ms: float | None = None
    """Milliseconds from sending the request to receiving the response. `None` when it isn't known, like when nothing
    was sent."""
    usage: Usage = Field(default_factory=Usage)
    """Token counts the server reports."""
    cost_usd: float | None = None
    """`None` when the target's price or token count is unknown."""
    warnings: list[ResultWarning] = Field(default_factory=list[ResultWarning])
    """Things a person should know about the result. A warning doesn't stop the result from counting."""
    error: ResultError | None = None
    """Why the target returned no answers. `None` when `ok` is `True`."""
    answers: dict[str, Answer] = Field(default_factory=dict[str, Answer])
    """Answers keyed by question id, in the request's question order. Empty when `ok` is `False`."""
    request_body: JsonValue = None
    """The exact body sent to the server. `None` when nothing was sent, and in a run's `result` events."""
    raw: JsonValue = None
    """The server's response body, unchanged. For Workers AI, it's the whole Cloudflare response. `None` when no
    response arrived, and in a run's `result` events."""
