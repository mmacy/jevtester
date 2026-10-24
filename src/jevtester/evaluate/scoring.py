"""Turn an answer into a comparable value, and score it against a case's expectation."""

from jevtester.normalize import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer
from jevtester.schemas import AnswerValue
from jevtester.spec import ChoiceQuestion, Expectation, Question

NOUL_THRESHOLD = 0.5
"""A noul answer is yes when the probability of yes is at least this."""

ABSTENTION_OPTIONS = frozenset({"abstain", "cannot_tell", "cant_tell", "unclear", "unknown", "unsure"})
"""Choice option names that mean the model abstained. Abstention is reported apart from accuracy."""


def answer_value(answer: Answer) -> AnswerValue | None:
    """Reduce an answer to the value an expectation names.

    Args:
        answer: A canonical answer.

    Returns:
        `True` or `False` for a noul, the chosen option for a choice, or the most probable level for a score. `None`
        for a score with no level probabilities.
    """
    match answer:
        case NoulAnswer():
            return answer.probability >= NOUL_THRESHOLD
        case ChoiceAnswer():
            return answer.choice
        case ScoreAnswer():
            return answer.level


def answer_probability(answer: Answer) -> float | None:
    """Return the probability the target gave its own answer.

    Args:
        answer: A canonical answer.

    Returns:
        For a noul, the probability of the side chosen. For a choice or a score, the probability of the chosen option
        or level. `None` when it's missing.
    """
    match answer:
        case NoulAnswer():
            return answer.probability if answer.probability >= NOUL_THRESHOLD else 1 - answer.probability
        case ChoiceAnswer():
            return answer.probabilities.get(answer.choice)
        case ScoreAnswer():
            return answer.probabilities[answer.level] if answer.level is not None else None


def is_correct(expectation: Expectation | None, answer: Answer | None) -> bool | None:
    """Check an answer against a case's expectation.

    Args:
        expectation: What the case expects, or `None`.
        answer: The target's answer, or `None` when it gave none.

    Returns:
        `None` when the case expects nothing for the question. Otherwise whether the answer matches the expected
        answer or one of the acceptable ones, with a score allowed `tolerance` levels of slack. A missing answer is
        wrong.
    """
    if expectation is None or expectation.answer is None:
        return None
    if answer is None:
        return False
    value = answer_value(answer)
    if value is None:
        return False
    acceptable = expectation.acceptable or []
    if isinstance(answer, ScoreAnswer):
        assert isinstance(value, int)
        expected = expectation.answer
        level = expected if isinstance(expected, int) and not isinstance(expected, bool) else None
        if level is not None and abs(value - level) <= expectation.tolerance:
            return True
        return value in acceptable
    return value == expectation.answer or (not isinstance(value, bool) and value in acceptable)


def abstention_option(question: Question) -> str | None:
    """Find a choice question's abstention option, like `cannot_tell`.

    Args:
        question: The question.

    Returns:
        The first option whose name is in [`ABSTENTION_OPTIONS`][jevtester.evaluate.scoring.ABSTENTION_OPTIONS], or
        `None`.
    """
    if not isinstance(question, ChoiceQuestion):
        return None
    return next((option for option in question.criteria if option in ABSTENTION_OPTIONS), None)
