"""Apply a policy to a result's answers, measure its decisions, and sweep a threshold."""

from collections.abc import Mapping, Sequence

from jevtester.normalize import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer, TargetResult
from jevtester.schemas import BandLevel, DecisionMetrics, PolicyDecision, SweepPoint
from jevtester.spec import Case, Question, ScoreQuestion
from jevtester.spec.policy import Bound, Condition, Policy, Range
from jevtester.store.runs import StoredResult

_BAND_ORDER: dict[BandLevel, int] = {"act": 0, "confirm": 1, "escalate": 2}


class _Thresholds:
    def __init__(self, policy: Policy, target: str | None, overrides: Mapping[str, float]) -> None:
        self._policy = policy
        self._target = target
        self._overrides = overrides

    def value(self, bound: Bound) -> float:
        if isinstance(bound, str):
            return self._overrides.get(bound, self._policy.threshold(bound, self._target))
        return bound


def _confidence(answer: Answer) -> float | None:
    return answer.confidence if answer.confidence is not None else answer.server_confidence


def _normalized(answer: Answer, question: Question | None) -> float | None:
    match answer:
        case NoulAnswer():
            return answer.probability
        case ChoiceAnswer():
            return answer.probabilities.get(answer.choice)
        case ScoreAnswer():
            top = len(question.criteria) - 1 if isinstance(question, ScoreQuestion) else len(answer.legend) - 1
            return answer.score / top if top > 0 else None


def _in_range(value: float | None, condition: Range, thresholds: _Thresholds) -> bool:
    if value is None:
        return False
    if condition.at_least is not None and value < thresholds.value(condition.at_least):
        return False
    return condition.at_most is None or value <= thresholds.value(condition.at_most)


def _holds(condition: Condition, answer: Answer | None, thresholds: _Thresholds) -> bool:
    match condition, answer:
        case Range(), NoulAnswer():
            return _in_range(answer.probability, condition, thresholds)
        case Range(), ChoiceAnswer():
            return _in_range(answer.probabilities.get(answer.choice), condition, thresholds)
        case Range(), ScoreAnswer():
            return _in_range(answer.score, condition, thresholds)
        case bool(), NoulAnswer():
            return (answer.probability >= 0.5) == condition
        case str(), ChoiceAnswer():
            return answer.choice == condition
        case list(), ChoiceAnswer():
            return answer.choice in condition
        case _:
            return False


def decide(
    policy: Policy,
    questions: Mapping[str, Question],
    answers: Mapping[str, Answer],
    *,
    target: str | None = None,
    overrides: Mapping[str, float] | None = None,
) -> PolicyDecision:
    """Choose an action from one result's answers.

    The bands come first: a banded question whose confidence is below its `confirm` value, or that has no answer,
    escalates. Otherwise the first rule whose conditions all hold gives the action, or the default when none does.

    Args:
        policy: The policy.
        questions: The questions asked, for each score's number of levels.
        answers: The answers, keyed by question id.
        target: The target that answered, for its threshold values.
        overrides: Threshold values to use instead of the policy's, for a sweep.

    Returns:
        The decision, with the band, the rule that matched, and each composite's value.
    """
    thresholds = _Thresholds(policy, target, overrides or {})
    composites: dict[str, float | None] = {}
    for name, weights in policy.composites.items():
        parts = [
            (weight, _normalized(answers[key], questions.get(key)) if key in answers else None)
            for key, weight in weights.items()
        ]
        composites[name] = None if any(v is None for _, v in parts) else sum(w * (v or 0.0) for w, v in parts)

    band: BandLevel = "act"
    for key, limits in policy.bands.items():
        answer = answers.get(key)
        confidence = _confidence(answer) if answer is not None else None
        if confidence is None:
            reason = f"{key} has no answer" if answer is None else f"{key} has no confidence"
            return PolicyDecision(
                action=policy.escalate, band="escalate", escalated=True, rule=None, composites=composites, reason=reason
            )
        confirm = thresholds.value(limits.confirm)
        if confidence < confirm:
            reason = f"{key} confidence {confidence:.3f} is below {confirm:g}"
            return PolicyDecision(
                action=policy.escalate, band="escalate", escalated=True, rule=None, composites=composites, reason=reason
            )
        level: BandLevel = "act" if confidence >= thresholds.value(limits.act) else "confirm"
        band = max(band, level, key=_BAND_ORDER.__getitem__)

    for index, rule in enumerate(policy.rules):
        matched = True
        for key, condition in rule.when.items():
            if key in policy.composites:
                value = composites[key]
                matched = isinstance(condition, Range) and _in_range(value, condition, thresholds)
            else:
                matched = _holds(condition, answers.get(key), thresholds)
            if not matched:
                break
        if matched:
            return PolicyDecision(action=rule.action, band=band, escalated=False, rule=index, composites=composites)
    return PolicyDecision(
        action=policy.default, band=band, escalated=False, rule=None, composites=composites, reason="No rule matched"
    )


def decide_result(
    policy: Policy,
    questions: Mapping[str, Question],
    result: TargetResult,
    overrides: Mapping[str, float] | None = None,
) -> PolicyDecision | None:
    """Decide from a target's result.

    Args:
        policy: The policy.
        questions: The questions asked.
        result: The target's result.
        overrides: Threshold values to use instead of the policy's.

    Returns:
        The decision, or `None` when the target failed.
    """
    if not result.ok:
        return None
    return decide(policy, questions, result.answers, target=result.target, overrides=overrides)


def _cost(policy: Policy, expected: str, chosen: str) -> float:
    if chosen == expected:
        return 0.0
    assert policy.costs is not None
    return policy.costs.get(expected, {}).get(chosen, 1.0)


def decision_metrics(
    policy: Policy,
    questions: Mapping[str, Question],
    results: Sequence[StoredResult],
    cases: Mapping[str, Case],
    overrides: Mapping[str, float] | None = None,
) -> DecisionMetrics:
    """Measure one target's decisions against the cases' expected actions.

    Args:
        policy: The policy.
        questions: The questions asked.
        results: One target's results for the original cases.
        cases: The run's cases by id.
        overrides: Threshold values to use instead of the policy's, for a sweep.

    Returns:
        Decision accuracy over every case with an expected action, the share decided without a band escalation, the
        error rate among those, and the total cost when the policy has a cost matrix. A failed result counts as an
        escalation.
    """
    pairs: list[tuple[str, PolicyDecision | None]] = []
    for stored in results:
        case = cases.get(stored.case_id)
        if case is None or case.expected_action is None:
            continue
        pairs.append((case.expected_action, decide_result(policy, questions, stored.result, overrides)))
    if not pairs:
        return DecisionMetrics(n=0, accuracy=None, decided_share=None, error_rate=None, cost=None)
    decided = [(expected, d) for expected, d in pairs if d is not None and not d.escalated]
    correct = sum(1 for expected, d in pairs if d is not None and d.action == expected)
    wrong_decided = sum(1 for expected, d in decided if d.action != expected)
    cost: float | None = None
    if policy.costs is not None:
        cost = sum(_cost(policy, expected, d.action if d is not None else policy.escalate) for expected, d in pairs)
    return DecisionMetrics(
        n=len(pairs),
        accuracy=correct / len(pairs),
        decided_share=len(decided) / len(pairs),
        error_rate=wrong_decided / len(decided) if decided else None,
        cost=cost,
    )


def sweep(
    policy: Policy,
    threshold: str,
    values: Sequence[float],
    questions: Mapping[str, Question],
    results: Sequence[StoredResult],
    cases: Mapping[str, Case],
) -> list[SweepPoint]:
    """Measure a target's decisions as one threshold moves.

    Args:
        policy: The policy.
        threshold: The threshold to move.
        values: The values to try.
        questions: The questions asked.
        results: One target's results for the original cases.
        cases: The run's cases by id.

    Returns:
        One point per value, with the share decided, the error rate, and the cost.
    """
    points: list[SweepPoint] = []
    for value in values:
        metrics = decision_metrics(policy, questions, results, cases, {threshold: value})
        points.append(
            SweepPoint(
                value=value, decided_share=metrics.decided_share, error_rate=metrics.error_rate, cost=metrics.cost
            )
        )
    return points
