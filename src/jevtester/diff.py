"""Compare two versions of a question set."""

from typing import Literal

from jevtester.schemas import DiffStatus, OptionDiff, QuestionDiff, QuestionSetDiff
from jevtester.spec import ChoiceQuestion, NoulQuestion, Question, QuestionSet

type ChangedField = Literal["type", "instructions", "criteria"]


def _options(question: Question) -> dict[str, str]:
    match question:
        case ChoiceQuestion():
            return dict(question.criteria)
        case NoulQuestion():
            criteria = question.criteria
            if criteria is None:
                return {}
            return {
                key: value for key, value in (("true", criteria.true), ("false", criteria.false)) if value is not None
            }
        case _:
            return {str(level): text for level, text in enumerate(question.criteria)}


def _option_diffs(before: dict[str, str], after: dict[str, str]) -> list[OptionDiff]:
    diffs: list[OptionDiff] = []
    for key, text in after.items():
        old = before.get(key)
        status: DiffStatus = "added" if old is None else "unchanged" if old == text else "changed"
        diffs.append(OptionDiff(key=key, status=status, before=old, after=text))
    diffs.extend(
        OptionDiff(key=key, status="removed", before=text, after=None)
        for key, text in before.items()
        if key not in after
    )
    return diffs


def diff_question_sets(before: QuestionSet, after: QuestionSet) -> QuestionSetDiff:
    """List how each question changed between two versions.

    Args:
        before: The older version.
        after: The newer version.

    Returns:
        One entry per question: the newer version's questions in order, then removed ones. Options and levels are
        compared by name for a choice and by index for a score.
    """
    questions: list[QuestionDiff] = []
    for key, new in after.questions.items():
        old = before.questions.get(key)
        if old is None:
            options = _option_diffs({}, _options(new))
            questions.append(
                QuestionDiff(
                    id=key,
                    status="added",
                    before=None,
                    after=new,
                    changed_fields=[],
                    options=options,
                    order_changed=False,
                )
            )
            continue
        changed: list[ChangedField] = []
        if old.type != new.type:
            changed.append("type")
        if old.instructions != new.instructions:
            changed.append("instructions")
        old_options, new_options = _options(old), _options(new)
        shared_old = [option for option in old_options if option in new_options]
        shared_new = [option for option in new_options if option in old_options]
        order_changed = isinstance(new, ChoiceQuestion) and shared_old != shared_new
        # Dict comparison ignores order, so a reordered choice counts through order_changed.
        if old_options != new_options or order_changed:
            changed.append("criteria")
        status: DiffStatus = "changed" if changed else "unchanged"
        questions.append(
            QuestionDiff(
                id=key,
                status=status,
                before=old,
                after=new,
                changed_fields=changed,
                options=_option_diffs(old_options, new_options) if status == "changed" else [],
                order_changed=order_changed,
            )
        )
    for key, old in before.questions.items():
        if key not in after.questions:
            questions.append(
                QuestionDiff(
                    id=key,
                    status="removed",
                    before=old,
                    after=None,
                    changed_fields=[],
                    options=_option_diffs(_options(old), {}),
                    order_changed=False,
                )
            )
    return QuestionSetDiff(name=after.name, from_version=before.version, to_version=after.version, questions=questions)
