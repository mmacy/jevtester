"""Map a System One response to canonical answers, and recompute confidence.

The normalizer reads the response body as plain JSON instead of through the TypeSafe SDK's strict models, so a server
that sends a slightly different format still yields answers, with a warning for each difference.
"""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from jevtester.normalize.answers import Answer, ChoiceAnswer, NoulAnswer, ResultWarning, ScoreAnswer, Usage
from jevtester.spec import Capabilities, ChoiceQuestion, NoulQuestion, Question, ScoreQuestion


class _WireNoul(BaseModel):
    noul: float
    confidence: float | None = None


class _WireChoice(BaseModel):
    choice: str
    probabilities: dict[str, float]
    confidence: float | None = None


class _WireScore(BaseModel):
    score: float
    probabilities: dict[str, float]
    confidence: float | None = None


class _WireUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class InvalidResponseError(ValueError):
    """The response body has no `answers` object, so no answer can be read from it."""


def noul_confidence(probability: float) -> float:
    """Compute a noul answer's confidence as `|2p - 1|`.

    Args:
        probability: The probability of yes.

    Returns:
        0 when the answer is a coin flip, and 1 when it's certain either way.
    """
    return abs(2 * probability - 1)


def choice_confidence(probabilities: Mapping[str, float], option_count: int | None = None) -> float:
    """Compute a choice answer's confidence as `(p_max - 1/n) / (1 - 1/n)`.

    Args:
        probabilities: The probability of each option.
        option_count: The question's number of options, `n`. `None` uses the number of probabilities.

    Returns:
        0 when every option is equally likely, and 1 when one option has all the probability.
    """
    n = len(probabilities) if option_count is None else option_count
    if n < 2:
        return 1.0
    p_max = max(probabilities.values(), default=0.0)
    return (p_max - 1 / n) / (1 - 1 / n)


def cost_usd(usage: Usage, capabilities: Capabilities) -> float | None:
    """Compute a request's cost from its input tokens.

    Args:
        usage: The token counts the server reported.
        capabilities: The target's capabilities, which hold its price.

    Returns:
        The cost in US dollars, or `None` when the price or the token count is unknown.
    """
    if usage.input_tokens is None or capabilities.input_cost_per_mtok_usd is None:
        return None
    return usage.input_tokens * capabilities.input_cost_per_mtok_usd / 1_000_000


def normalize_usage(body: Mapping[str, Any]) -> Usage:
    """Read the token counts from a System One response body.

    Args:
        body: The System One response body.

    Returns:
        The token counts, with `None` for any the server didn't report.
    """
    try:
        wire = _WireUsage.model_validate(body.get("usage") or {})
    except ValidationError:
        return Usage()
    return Usage(input_tokens=wire.input_tokens, output_tokens=wire.output_tokens)


def normalize(
    questions: Mapping[str, Question], body: Mapping[str, Any]
) -> tuple[dict[str, Answer], list[ResultWarning]]:
    """Map a System One response body to one canonical answer per question.

    Args:
        questions: The questions sent, keyed by id.
        body: The System One response body. For Workers AI, the `result` inside the Cloudflare envelope.

    Returns:
        The answers in the order of `questions`, and a warning for each answer that is missing, malformed, or names
        an option the question doesn't have. A malformed answer is left out.

    Raises:
        InvalidResponseError: The body has no `answers` object.
    """
    raw_answers = body.get("answers")
    if not isinstance(raw_answers, dict):
        raise InvalidResponseError("The response has no answers object.")
    raw_by_id = cast(dict[str, Any], raw_answers)

    answers: dict[str, Answer] = {}
    warnings: list[ResultWarning] = []
    for key, question in questions.items():
        raw = raw_by_id.get(key)
        if raw is None:
            warnings.append(ResultWarning(code="missing_answer", message="The response has no answer.", question=key))
            continue
        try:
            answer, answer_warnings = _normalize_answer(key, question, raw)
        except (ValidationError, _TypeMismatchError) as error:
            warnings.append(ResultWarning(code="invalid_answer", message=_describe(error), question=key))
            continue
        answers[key] = answer
        warnings.extend(answer_warnings)
    for key in raw_by_id.keys() - questions.keys():
        warnings.append(
            ResultWarning(code="unexpected_answer", message="The response answers a question not asked.", question=key)
        )
    return answers, warnings


class _TypeMismatchError(Exception):
    pass


def _describe(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first["loc"])
        return f"{location}: {first['msg']}" if location else first["msg"]
    return str(error)


def _normalize_answer(key: str, question: Question, raw: Any) -> tuple[Answer, list[ResultWarning]]:
    answer_type = cast(dict[str, Any], raw).get("type") if isinstance(raw, dict) else None
    if answer_type != question.type:
        raise _TypeMismatchError(f"Expected a {question.type} answer, got {answer_type!r}.")
    match question:
        case NoulQuestion():
            return _normalize_noul(raw), []
        case ChoiceQuestion():
            return _normalize_choice(key, question, raw)
        case ScoreQuestion():
            return _normalize_score(key, question, raw)


def _normalize_noul(raw: Any) -> NoulAnswer:
    wire = _WireNoul.model_validate(raw)
    return NoulAnswer(probability=wire.noul, confidence=noul_confidence(wire.noul), server_confidence=wire.confidence)


def _normalize_choice(key: str, question: ChoiceQuestion, raw: Any) -> tuple[ChoiceAnswer, list[ResultWarning]]:
    wire = _WireChoice.model_validate(raw)
    warnings: list[ResultWarning] = []
    options = question.criteria
    probabilities = {option: wire.probabilities[option] for option in options if option in wire.probabilities}
    missing = [option for option in options if option not in wire.probabilities]
    if missing:
        warnings.append(
            ResultWarning(code="missing_probability", message=f"No probability for {', '.join(missing)}.", question=key)
        )
    unknown = [option for option in wire.probabilities if option not in options]
    if wire.choice not in options and wire.choice not in unknown:
        unknown.insert(0, wire.choice)
    if unknown:
        warnings.append(
            ResultWarning(
                code="unknown_option", message=f"The question has no option {', '.join(unknown)}.", question=key
            )
        )
    answer = ChoiceAnswer(
        choice=wire.choice,
        probabilities=probabilities,
        confidence=choice_confidence(probabilities, len(options)),
        server_confidence=wire.confidence,
    )
    return answer, warnings


def _normalize_score(key: str, question: ScoreQuestion, raw: Any) -> tuple[ScoreAnswer, list[ResultWarning]]:
    wire = _WireScore.model_validate(raw)
    warnings: list[ResultWarning] = []
    levels = [str(level) for level in range(len(question.criteria))]
    missing = [level for level in levels if level not in wire.probabilities]
    if missing:
        warnings.append(
            ResultWarning(
                code="missing_probability", message=f"No probability for level {', '.join(missing)}.", question=key
            )
        )
    unknown = [level for level in wire.probabilities if level not in levels]
    if unknown:
        warnings.append(
            ResultWarning(
                code="unknown_option", message=f"The question has no level {', '.join(unknown)}.", question=key
            )
        )
    answer = ScoreAnswer(
        score=wire.score,
        probabilities=[wire.probabilities.get(level, 0.0) for level in levels],
        legend=list(question.criteria),
        server_confidence=wire.confidence,
    )
    return answer, warnings
