"""Check a suite's cases against its question set, and check question wording against the vendors' guidance."""

import re

from jevtester.evaluate.scoring import abstention_option
from jevtester.schemas import ErrorDetail, WordingCheck
from jevtester.spec import ChoiceQuestion, NoulQuestion, Question, QuestionSet, ScoreQuestion, Suite

DEGREE_WORDS = frozenset(
    {
        "extremely",
        "fairly",
        "highly",
        "mildly",
        "moderate",
        "moderately",
        "quite",
        "rather",
        "slightly",
        "somewhat",
        "very",
    }
)
"""Words that describe a degree instead of a situation. The vendors say concrete criteria score better."""

_WORD = re.compile(r"[a-z']+")
_BARE_NUMBER = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")


def _degree_words(text: str) -> list[str]:
    return sorted({word for word in _WORD.findall(text.lower()) if word in DEGREE_WORDS})


def _criteria_texts(question: Question) -> list[str]:
    match question:
        case ChoiceQuestion():
            return list(question.criteria.values())
        case ScoreQuestion():
            return list(question.criteria)
        case NoulQuestion():
            criteria = question.criteria
            return [text for text in (criteria.true, criteria.false) if text] if criteria else []


def wording_checks(question_set: QuestionSet) -> list[WordingCheck]:
    """Check each question against the vendors' guidance for writing questions.

    The checks are heuristics. Each finding is a prompt to look at the wording, not proof it's wrong.

    Args:
        question_set: The questions.

    Returns:
        A finding for a question that asks two things at once, criteria that name degrees, score levels that are only
        numbers, a choice with no abstention option, and options or levels with the same description.
    """
    checks: list[WordingCheck] = []
    for key, question in question_set.questions.items():
        if question.instructions.count("?") > 1:
            checks.append(WordingCheck(question=key, code="multiple_dimensions", message="Asks more than one question"))
        degrees = sorted({word for text in _criteria_texts(question) for word in _degree_words(text)})
        if degrees:
            checks.append(
                WordingCheck(
                    question=key, code="degree_words", message=f"Criteria use degree words: {', '.join(degrees)}"
                )
            )
        if isinstance(question, ScoreQuestion) and any(_BARE_NUMBER.match(level) for level in question.criteria):
            checks.append(WordingCheck(question=key, code="bare_number_levels", message="Some levels are only numbers"))
        if isinstance(question, ChoiceQuestion) and abstention_option(question) is None:
            checks.append(WordingCheck(question=key, code="no_abstention", message="No option like cannot_tell"))
        texts = [text.strip().lower() for text in _criteria_texts(question) if text.strip()]
        if len(set(texts)) < len(texts):
            checks.append(
                WordingCheck(question=key, code="duplicate_options", message="Two options have the same description")
            )
    return checks


def case_errors(suite: Suite, question_set: QuestionSet) -> list[ErrorDetail]:
    """Check that every case's expectations fit the question set.

    Args:
        suite: The suite.
        question_set: Its question set.

    Returns:
        An error for each expectation that names a missing question, a missing option, a level out of range, or a
        value of the wrong type, and for each case id used twice.
    """
    errors: list[ErrorDetail] = []
    seen: set[str] = set()
    for index, case in enumerate(suite.cases):
        if case.id in seen:
            errors.append(ErrorDetail(field=f"cases.{index}.id", message=f"The case id {case.id} is used twice"))
        seen.add(case.id)
        for key, expectation in case.expected.items():
            field = f"cases.{index}.expected.{key}"
            question = question_set.questions.get(key)
            if question is None:
                errors.append(
                    ErrorDetail(field=field, message=f"{case.id} expects an answer to {key}, which isn't asked")
                )
                continue
            values = [expectation.answer, *(expectation.acceptable or [])]
            for value in (v for v in values if v is not None):
                problem = _value_problem(question, value)
                if problem:
                    errors.append(ErrorDetail(field=field, message=f"{case.id}: {problem}"))
    return errors


def _value_problem(question: Question, value: bool | str | int) -> str | None:
    match question:
        case NoulQuestion():
            return None if isinstance(value, bool) else f"a noul expects true or false, not {value!r}"
        case ChoiceQuestion():
            if not isinstance(value, str):
                return f"a choice expects an option name, not {value!r}"
            return None if value in question.criteria else f"{value} isn't an option"
        case ScoreQuestion():
            if isinstance(value, bool) or not isinstance(value, int):
                return f"a score expects a level number, not {value!r}"
            last = len(question.criteria) - 1
            return None if 0 <= value <= last else f"level {value} is outside 0 to {last}"
