"""A run's report as Markdown."""

from jevtester.schemas import RunChanges, RunMetrics, RunSummary


def _number(value: float | None, digits: int = 3) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def _cost(value: float | None) -> str:
    return "" if value is None else f"${value:.6f}"


def report_markdown(summary: RunSummary, metrics: RunMetrics, changes: RunChanges | None = None) -> str:
    """Write a run's summary, metrics, and changes as Markdown.

    Args:
        summary: The run.
        metrics: Its metrics.
        changes: Its changes from the baseline, when it has one.

    Returns:
        The report, ending with a newline.
    """
    counts = summary.counts
    lines = [
        f"# Run {summary.id}: {summary.suite}",
        "",
        f"- Status: {summary.status}",
        f"- Question set: `{summary.question_set}` version `{summary.question_set_version[:12]}`",
        f"- Cases: {summary.case_count}, repeats: {summary.repeats}",
        f"- Jobs: {counts.jobs}, sent {counts.sent}, from cache {counts.cached}, failed {counts.failed}, "
        f"skipped {counts.skipped}",
        f"- Cost: {_cost(summary.cost_usd) or 'unknown'}",
    ]
    if summary.baseline:
        lines.append(f"- Baseline: run {summary.baseline}")
    lines += [
        "",
        "## Targets",
        "",
        "| Target | Results | Errors | Skipped | p50 latency (ms) | p95 latency (ms) | Cost per 1,000 |",
        "|---|---|---|---|---|---|---|",
    ]
    for target in metrics.targets:
        lines.append(
            f"| {target.target} | {target.results} | {target.errors} | {target.skipped} "
            f"| {_number(target.latency_p50_ms, 0)} | {_number(target.latency_p95_ms, 0)} "
            f"| {_cost(target.cost_per_1k_usd)} |"
        )
    for question_id in metrics.questions:
        lines += [
            "",
            f"## {question_id}",
            "",
            "| Target | n | Accuracy | Macro-F1 | MAE | Within tolerance | Brier | Log loss | AUROC | ECE |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for target in metrics.targets:
            row = next((q for q in target.questions if q.question == question_id), None)
            if row is None:
                lines.append(f"| {target.target} | 0 | | | | | | | | |")
                continue
            values = [
                row.accuracy,
                row.macro_f1,
                row.mae,
                row.within_tolerance,
                row.brier,
                row.log_loss,
                row.auroc,
                row.ece,
            ]
            lines.append(f"| {target.target} | {row.n} | " + " | ".join(_number(v) for v in values) + " |")
    decided = [target for target in metrics.targets if target.decision is not None]
    if decided:
        lines += [
            "",
            f"## Decisions with policy `{summary.policy}`",
            "",
            "| Target | n | Accuracy | Decided | Error rate when decided | Cost |",
            "|---|---|---|---|---|---|",
        ]
        for target in decided:
            d = target.decision
            assert d is not None
            lines.append(
                f"| {target.target} | {d.n} | {_number(d.accuracy)} | {_number(d.decided_share)} "
                f"| {_number(d.error_rate)} | {_number(d.cost, 1)} |"
            )
    if changes is not None:
        lines += ["", f"## Changes from run {changes.baseline}", ""]
        if not changes.changes:
            lines.append("No answers changed.")
        else:
            lines += [
                "| Case | Target | Question | Baseline | Now | Expected | Status |",
                "|---|---|---|---|---|---|---|",
            ]
            for change in changes.changes:
                lines.append(
                    f"| {change.case_id} | {change.target} | {change.question} | {change.baseline_answer} "
                    f"| {change.answer} | {change.expected} | {change.status} |"
                )
        lines += ["", "| Target | Fixed | Broken | Changed | McNemar p |", "|---|---|---|---|---|"]
        for row in changes.summary:
            lines.append(f"| {row.target} | {row.fixed} | {row.broken} | {row.changed} | {_number(row.mcnemar_p)} |")
    return "\n".join(lines) + "\n"
