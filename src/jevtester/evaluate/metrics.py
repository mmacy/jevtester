"""Metrics for a run, comparisons between runs, and the tables behind them.

Every function here reads stored results and returns an API model. Only results for the original cases count:
probe variants are reported by the probe report.
"""

import math
from collections.abc import Mapping, Sequence
from statistics import mean

from jevtester.evaluate.scoring import abstention_option, answer_probability, answer_value, is_correct
from jevtester.normalize import Answer, ChoiceAnswer, NoulAnswer, ScoreAnswer
from jevtester.schemas import (
    AnswerChange,
    Calibration,
    CalibrationBin,
    ChangeStatus,
    ChangeSummary,
    ConfusionMatrix,
    QuestionMetrics,
    RunChanges,
    RunMetrics,
    RunSummary,
    TargetMetrics,
)
from jevtester.spec import Case, ChoiceQuestion, NoulQuestion, Question, ScoreQuestion, Target
from jevtester.store.runs import StoredResult

CALIBRATION_BINS = 10
LOG_LOSS_EPSILON = 1e-15


def originals(results: Sequence[StoredResult], target: str | None = None) -> list[StoredResult]:
    """Keep the results for the original cases, without probe variants.

    Args:
        results: A run's results.
        target: Keep only this target's results. `None` keeps every target's.

    Returns:
        The results, in the order they arrived.
    """
    return [r for r in results if r.variant is None and (target is None or r.target == target)]


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Interpolate a percentile.

    Args:
        values: The values.
        fraction: The percentile as a fraction, like 0.95.

    Returns:
        The percentile, or `None` when there are no values.
    """
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _macro_f1(pairs: Sequence[tuple[object, object]]) -> float | None:
    labels = {expected for expected, _ in pairs} | {answered for _, answered in pairs}
    if not labels:
        return None
    scores: list[float] = []
    for label in labels:
        true_positive = sum(1 for e, a in pairs if e == label and a == label)
        predicted = sum(1 for _, a in pairs if a == label)
        actual = sum(1 for e, _ in pairs if e == label)
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / actual if actual else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return mean(scores)


def _auroc(pairs: Sequence[tuple[float, bool]]) -> float | None:
    positives = [p for p, y in pairs if y]
    negatives = [p for p, y in pairs if not y]
    if not positives or not negatives:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def calibration_bins(
    pairs: Sequence[tuple[float, bool]], bin_count: int = CALIBRATION_BINS
) -> tuple[list[CalibrationBin], float | None]:
    """Build a reliability table and its expected calibration error.

    Args:
        pairs: Each predicted probability and whether the outcome happened.
        bin_count: The number of equal-width bins from 0 to 1.

    Returns:
        The bins, and the expected calibration error: the count-weighted mean gap between each bin's mean prediction
        and its observed rate. `None` when there are no pairs.
    """
    bins: list[CalibrationBin] = []
    gap = 0.0
    for index in range(bin_count):
        lower, upper = index / bin_count, (index + 1) / bin_count
        last = index == bin_count - 1
        members = [(p, y) for p, y in pairs if lower <= p < upper or (last and p == upper)]
        predicted = mean(p for p, _ in members) if members else None
        observed = sum(1 for _, y in members if y) / len(members) if members else None
        if predicted is not None and observed is not None:
            gap += len(members) * abs(predicted - observed)
        bins.append(
            CalibrationBin(
                lower=lower, upper=upper, count=len(members), mean_predicted=predicted, observed_rate=observed
            )
        )
    return bins, (gap / len(pairs) if pairs else None)


def _calibration_pairs(
    question: Question, results: Sequence[StoredResult], question_id: str, cases: Mapping[str, Case]
) -> list[tuple[float, bool]]:
    pairs: list[tuple[float, bool]] = []
    for stored in results:
        case = cases.get(stored.case_id)
        expectation = case.expected.get(question_id) if case else None
        answer = stored.result.answers.get(question_id)
        if expectation is None or expectation.answer is None or answer is None:
            continue
        match question, answer:
            case NoulQuestion(), NoulAnswer():
                pairs.append((answer.probability, bool(expectation.answer)))
            case ChoiceQuestion(), ChoiceAnswer():
                probability = answer.probabilities.get(answer.choice)
                correct = is_correct(expectation, answer)
                if probability is not None and correct is not None:
                    pairs.append((probability, correct))
            case _:
                pass
    return pairs


def _consistency(results: Sequence[StoredResult], question_id: str) -> float | None:
    by_case: dict[str, list[object]] = {}
    for stored in results:
        answer = stored.result.answers.get(question_id)
        by_case.setdefault(stored.case_id, []).append(answer_value(answer) if answer else None)
    repeated = [values for values in by_case.values() if len(values) > 1]
    if not repeated:
        return None
    return sum(1 for values in repeated if len(set(map(repr, values))) == 1) / len(repeated)


def question_metrics(
    question_id: str,
    question: Question,
    results: Sequence[StoredResult],
    cases: Mapping[str, Case],
    *,
    probabilities: bool,
) -> QuestionMetrics:
    """Compute one target's metrics for one question.

    Args:
        question_id: The question's id.
        question: The question.
        results: The target's results for the original cases.
        cases: The run's cases by id, for their expectations.
        probabilities: Whether the target returns probabilities. Calibration needs them.

    Returns:
        The metrics. A metric that doesn't apply to the question's type is `None`, and so is one with no scored
        answers.
    """
    scored: list[tuple[Case, Answer | None]] = []
    for stored in results:
        case = cases.get(stored.case_id)
        if case is None or not stored.result.ok:
            continue
        expectation = case.expected.get(question_id)
        if expectation is not None and expectation.answer is not None:
            scored.append((case, stored.result.answers.get(question_id)))
    correct = [bool(is_correct(case.expected[question_id], answer)) for case, answer in scored]
    metrics = QuestionMetrics(
        question=question_id,
        type=question.type,
        n=len(scored),
        accuracy=None,
        macro_f1=None,
        mae=None,
        within_tolerance=None,
        brier=None,
        log_loss=None,
        auroc=None,
        ece=None,
        abstention_rate=None,
        consistency=_consistency([r for r in results if r.result.ok], question_id),
    )
    if not scored:
        return metrics
    metrics.accuracy = sum(correct) / len(correct)
    match question:
        case ChoiceQuestion():
            pairs = [
                (case.expected[question_id].answer, answer_value(answer) if answer else None) for case, answer in scored
            ]
            metrics.macro_f1 = _macro_f1(pairs)
            abstain = abstention_option(question)
            if abstain is not None:
                chosen = [answer for _, answer in scored if isinstance(answer, ChoiceAnswer)]
                metrics.abstention_rate = (
                    sum(1 for a in chosen if a.choice == abstain) / len(chosen) if chosen else None
                )
        case ScoreQuestion():
            errors: list[float] = []
            exact: list[bool] = []
            for case, answer in scored:
                expected = case.expected[question_id].answer
                if isinstance(answer, ScoreAnswer) and isinstance(expected, int) and not isinstance(expected, bool):
                    errors.append(abs(answer.score - expected))
                    exact.append(answer.level == expected)
                else:
                    exact.append(False)
            metrics.accuracy = sum(exact) / len(exact)
            metrics.within_tolerance = sum(correct) / len(correct)
            metrics.mae = mean(errors) if errors else None
        case NoulQuestion():
            pairs = [
                (answer.probability, bool(case.expected[question_id].answer))
                for case, answer in scored
                if isinstance(answer, NoulAnswer)
            ]
            if pairs:
                metrics.brier = mean((p - y) ** 2 for p, y in pairs)
                metrics.log_loss = mean(-math.log(min(max(p if y else 1 - p, LOG_LOSS_EPSILON), 1.0)) for p, y in pairs)
                metrics.auroc = _auroc(pairs)
    if probabilities and isinstance(question, NoulQuestion | ChoiceQuestion):
        _, metrics.ece = calibration_bins(_calibration_pairs(question, results, question_id, cases))
    return metrics


def run_metrics(
    summary: RunSummary,
    results: Sequence[StoredResult],
    questions: Mapping[str, Question],
    cases: Mapping[str, Case],
    targets: Mapping[str, Target],
) -> RunMetrics:
    """Compute every target's metrics for a run.

    Args:
        summary: The run.
        results: The run's results.
        questions: The questions the run asked.
        cases: The run's cases by id.
        targets: The configured targets by name, for their capabilities.

    Returns:
        The metrics for each target in the run, in the run's target order.
    """
    rows: list[TargetMetrics] = []
    counts = {row.target: row for row in summary.counts.targets}
    for name in summary.targets:
        mine = originals(results, name)
        target = targets.get(name)
        probabilities = target.capabilities.probabilities if target else True
        ok = [r for r in mine if r.result.ok]
        latencies = [r.result.latency_ms for r in ok if r.result.latency_ms is not None]
        sent_costs = [r.result.cost_usd for r in mine if not r.cached and r.result.cost_usd is not None]
        all_costs = [r.result.cost_usd for r in ok if r.result.cost_usd is not None]
        row = counts.get(name)
        rows.append(
            TargetMetrics(
                target=name,
                results=len(mine),
                errors=sum(1 for r in mine if not r.result.ok),
                skipped=row.skipped if row else 0,
                probabilities=probabilities,
                latency_p50_ms=percentile(latencies, 0.5),
                latency_p95_ms=percentile(latencies, 0.95),
                cost_usd=sum(sent_costs) if sent_costs else (0.0 if mine and all(r.cached for r in mine) else None),
                cost_per_1k_usd=mean(all_costs) * 1000 if all_costs else None,
                questions=[
                    question_metrics(qid, question, mine, cases, probabilities=probabilities)
                    for qid, question in questions.items()
                ]
                if mine
                else [],
                decision=None,
            )
        )
    return RunMetrics(run_id=summary.id, questions=list(questions), targets=rows)


def confusion_matrix(
    run_id: str,
    target: str,
    question_id: str,
    question: ChoiceQuestion,
    results: Sequence[StoredResult],
    cases: Mapping[str, Case],
) -> ConfusionMatrix:
    """Count expected options against answered options.

    Args:
        run_id: The run's id.
        target: The target.
        question_id: The choice question's id.
        question: The choice question.
        results: The run's results.
        cases: The run's cases by id.

    Returns:
        The matrix, with the question's options in order and then any unknown option the target answered.
    """
    options = list(question.criteria)
    pairs: list[tuple[str, str]] = []
    for stored in originals(results, target):
        case = cases.get(stored.case_id)
        expectation = case.expected.get(question_id) if case else None
        answer = stored.result.answers.get(question_id)
        if expectation is None or not isinstance(expectation.answer, str) or not isinstance(answer, ChoiceAnswer):
            continue
        for option in (expectation.answer, answer.choice):
            if option not in options:
                options.append(option)
        pairs.append((expectation.answer, answer.choice))
    counts = [[0] * len(options) for _ in options]
    for expected, answered in pairs:
        counts[options.index(expected)][options.index(answered)] += 1
    recall = [row[i] / sum(row) if sum(row) else None for i, row in enumerate(counts)]
    return ConfusionMatrix(
        run_id=run_id,
        target=target,
        question=question_id,
        options=options,
        counts=counts,
        correct=sum(counts[i][i] for i in range(len(options))),
        total=len(pairs),
        recall=recall,
    )


def calibration(
    run_id: str,
    target: str,
    question_id: str,
    question: Question,
    results: Sequence[StoredResult],
    cases: Mapping[str, Case],
    bin_count: int = CALIBRATION_BINS,
) -> Calibration:
    """Build a reliability table for one question and one target.

    Args:
        run_id: The run's id.
        target: The target.
        question_id: The noul or choice question's id.
        question: The question.
        results: The run's results.
        cases: The run's cases by id.
        bin_count: The number of bins.

    Returns:
        The table. For a noul the prediction is the probability of yes. For a choice it's the probability of the
        chosen option, against whether that choice was correct.
    """
    pairs = _calibration_pairs(question, originals(results, target), question_id, cases)
    bins, ece = calibration_bins(pairs, bin_count)
    return Calibration(run_id=run_id, target=target, question=question_id, bins=bins, ece=ece, n=len(pairs))


def mcnemar_p(fixed: int, broken: int) -> float | None:
    """Compute McNemar's exact two-sided test on paired results.

    Args:
        fixed: Pairs wrong in the baseline and right now.
        broken: Pairs right in the baseline and wrong now.

    Returns:
        The p-value, or `None` when no pair changed between right and wrong.
    """
    n = fixed + broken
    if n == 0:
        return None
    tail = sum(math.comb(n, k) for k in range(min(fixed, broken) + 1)) / 2**n
    return min(1.0, 2 * tail)


def run_changes(
    run: RunSummary,
    baseline: RunSummary,
    results: Sequence[StoredResult],
    baseline_results: Sequence[StoredResult],
    cases: Mapping[str, Case],
    questions: Mapping[str, Question],
) -> RunChanges:
    """List the answers that changed from a baseline run.

    Args:
        run: The run.
        baseline: The baseline run.
        results: The run's results.
        baseline_results: The baseline's results.
        cases: The run's cases by id, for their expectations.
        questions: The run's questions. Only questions both runs asked are compared.

    Returns:
        Each changed answer on the first repeat of each case, for the targets both runs ran, with McNemar's test for
        each target.
    """

    def first(stored: Sequence[StoredResult]) -> dict[tuple[str, str], StoredResult]:
        return {(r.target, r.case_id): r for r in reversed(originals(stored)) if r.repeat == 0}

    now, before = first(results), first(baseline_results)
    changes: list[AnswerChange] = []
    summary: list[ChangeSummary] = []
    for target in (t for t in run.targets if t in baseline.targets):
        fixed = broken = changed = 0
        for case_id in dict.fromkeys(r.case_id for r in originals(results, target)):
            current, previous = now.get((target, case_id)), before.get((target, case_id))
            if current is None or previous is None:
                continue
            case = cases.get(case_id)
            for question_id in questions:
                if question_id not in previous.result.answers and question_id not in current.result.answers:
                    continue
                answer = current.result.answers.get(question_id)
                old = previous.result.answers.get(question_id)
                value = answer_value(answer) if answer else None
                old_value = answer_value(old) if old else None
                if value == old_value:
                    continue
                expectation = case.expected.get(question_id) if case else None
                was, now_correct = is_correct(expectation, old), is_correct(expectation, answer)
                status: ChangeStatus = "changed"
                if was is False and now_correct:
                    status = "fixed"
                elif was and now_correct is False:
                    status = "broken"
                fixed += status == "fixed"
                broken += status == "broken"
                changed += status == "changed"
                changes.append(
                    AnswerChange(
                        case_id=case_id,
                        target=target,
                        question=question_id,
                        expected=expectation.answer if expectation else None,
                        baseline_answer=old_value,
                        baseline_probability=answer_probability(old) if old else None,
                        answer=value,
                        probability=answer_probability(answer) if answer else None,
                        status=status,
                    )
                )
        summary.append(
            ChangeSummary(
                target=target, fixed=fixed, broken=broken, changed=changed, mcnemar_p=mcnemar_p(fixed, broken)
            )
        )
    return RunChanges(run_id=run.id, baseline=baseline.id, changes=changes, summary=summary)
