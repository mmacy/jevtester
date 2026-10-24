"""Request and response models for the operations in `service.py`.

The HTTP API returns these models as JSON, and the CLI's `--format json` output uses the same models, so scripts,
agents, and the UI parse one format. `docs/api.md` describes them, and `docs/openapi.json` is generated from them.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from jevtester.model import Model
from jevtester.normalize import ResultError, ResultWarning, TargetResult
from jevtester.spec import (
    Capabilities,
    Case,
    DecisionRequest,
    ProviderName,
    Question,
    QuestionSet,
    QuestionType,
    Suite,
)

type AnswerValue = bool | str | int
"""A comparable answer: `True` or `False` for a noul, an option name for a choice, or a level for a score."""

# Errors


type ApiErrorCode = Literal["invalid_request", "not_found", "conflict", "not_ready", "internal"]
"""Why a request failed. The HTTP status matches: 422, 404, 409, 409, and 500."""


class ErrorDetail(Model):
    """One validation error."""

    field: str | None = None
    """The dotted path of the field, like `questions.intent.criteria`. `None` for the whole input."""
    message: str


class ApiErrorBody(Model):
    """What went wrong."""

    code: ApiErrorCode
    message: str
    field: str | None = None
    """The dotted path of the first invalid field, when the error is about one."""
    details: list[ErrorDetail] = Field(default_factory=list[ErrorDetail])
    """Every validation error, for a form or editor that shows them all."""


class ApiError(Model):
    """The body of every 4xx and 5xx response."""

    error: ApiErrorBody


# Targets


type TargetStatus = Literal["ready", "warning", "down", "unchecked"]
"""`down` when the last health check gave a reason, `warning` when the target is ready and has warnings, `ready`
otherwise, and `unchecked` before the first health check."""


class TargetInfo(Model):
    """A target, its capabilities, and its last health check."""

    name: str
    label: str
    provider: ProviderName
    model: str
    base_url: str | None
    local: bool
    """Whether the target runs on this machine. Local targets cost nothing."""
    status: TargetStatus
    reason: str | None = None
    """Why the target is down, like `Ollama isn't running`."""
    detail: str | None = None
    """What to do about it, or more about the target's state, like `Needs 0.35.1 or later`."""
    credential: str | None = None
    """Where the credential comes from and when it expires, like `Azure CLI, refreshes in 41 min`."""
    warnings: list[ResultWarning] = Field(default_factory=list[ResultWarning])
    """Warnings that apply to every request, like `truncation_on`."""
    checked_at: datetime | None = None
    capabilities: Capabilities


class TargetList(Model):
    """Every configured target."""

    targets: list[TargetInfo]
    default_targets: list[str]
    """The targets a request goes to when it names none, from the config's `defaults.targets`, in order."""
    checked_at: datetime | None = None
    """When the last health check ran. `None` before the first one."""


# Decide


class DecideBody(DecisionRequest):
    """One request to send to one or more targets."""

    targets: list[str] = Field(default_factory=list[str])
    """Target names. Empty means the config's default targets."""
    timeout_s: float | None = Field(default=None, gt=0)
    """Seconds to wait for each target. `None` uses the config's default."""


class DecideResponse(Model):
    """One result per target, in the order the targets were named."""

    request: DecisionRequest
    question_set_version: str
    """The hash of the request's questions, as a question set with them would have."""
    asked_at: datetime
    results: list[TargetResult]


# Suites and cases


class SuiteSummary(Model):
    """A suite in the list of suites."""

    name: str
    question_set: str
    question_set_version: str | None
    """The current version of the suite's question set. `None` when the question set doesn't exist."""
    policy: str | None
    targets: list[str]
    case_count: int
    """Cases that count in evaluation. Claude drafts aren't included."""
    draft_count: int
    """Cases with `provenance: "claude-draft"`."""


class SuiteList(Model):
    """Every suite under `suites/`."""

    suites: list[SuiteSummary]


class SuiteDetail(Model):
    """A suite with its cases and its question set."""

    suite: Suite
    question_set: QuestionSet


class CaseCreated(Model):
    """A case saved to a suite."""

    suite: str
    case: Case
    case_count: int


type WordingCheckCode = Literal[
    "multiple_dimensions", "degree_words", "bare_number_levels", "no_abstention", "duplicate_options"
]
"""Which of the vendors' question-writing rules a question may break."""


class WordingCheck(Model):
    """A finding from the question-wording checks."""

    question: str
    code: WordingCheckCode
    message: str


class SuiteCheck(Model):
    """The result of `jevtester suite check`."""

    suite: str
    valid: bool
    """Whether the suite, its question set, and its policy load, and every case's expectations name real questions."""
    errors: list[ErrorDetail]
    checks: list[WordingCheck]


# Question sets


class QuestionSetSummary(Model):
    """A question set in the list of question sets."""

    name: str
    version: str
    question_count: int
    suites: list[str]
    """Suites that use this question set."""
    updated_at: datetime | None
    """When the current version was first seen."""


class QuestionSetList(Model):
    """Every question set under `suites/`."""

    question_sets: list[QuestionSetSummary]


class QuestionSetDetail(Model):
    """A question set's current version, the suites that use it, and its wording checks."""

    question_set: QuestionSet
    suites: list[str]
    checks: list[WordingCheck]


class QuestionSetBody(Model):
    """The questions to save as a question set's new version."""

    questions: dict[str, Question] = Field(min_length=1)


class QuestionSetVersion(Model):
    """One version of a question set."""

    version: str
    first_seen: datetime
    question_count: int
    run_count: int
    """Runs that used this version."""
    current: bool
    """Whether this is the version in the YAML file now."""


class QuestionSetVersions(Model):
    """A question set's versions, newest first."""

    name: str
    versions: list[QuestionSetVersion]


type DiffStatus = Literal["added", "removed", "changed", "unchanged"]


class OptionDiff(Model):
    """How one option or level changed."""

    key: str
    """The option name for a choice, or the level index for a score."""
    status: DiffStatus
    before: str | None
    after: str | None


class QuestionDiff(Model):
    """How one question changed between two versions."""

    id: str
    status: DiffStatus
    before: Question | None
    after: Question | None
    changed_fields: list[Literal["type", "instructions", "criteria"]]
    options: list[OptionDiff]
    """Options or levels in the newer version's order, then removed ones."""
    order_changed: bool
    """Whether the options that both versions have are in a different order."""


class QuestionSetDiff(Model):
    """The differences between two versions of a question set."""

    name: str
    from_version: str
    to_version: str
    questions: list[QuestionDiff]


# Runs


type RunKind = Literal["suite", "probe"]
type RunStatus = Literal["queued", "running", "finished", "cancelled", "failed"]
type ProbeVariant = Literal["option_order", "key_order", "bare_levels", "pad_state"]


class RunCreate(Model):
    """A run to start."""

    suite: str
    targets: list[str] = Field(default_factory=list[str])
    """Target names. Empty means the suite's default targets, or else the config's."""
    question_set_version: str | None = None
    """A question set version to run. `None` runs the current version."""
    repeats: int | None = Field(default=None, ge=1)
    """Times to send each request. `None` uses the config's default."""
    no_cache: bool = False
    """Send every request, even when a cached result exists."""
    baseline: str | None = None
    """A run to compare with when this one finishes."""


class ProbeCreate(Model):
    """A probe run to start."""

    suite: str
    targets: list[str] = Field(default_factory=list[str])
    variants: list[ProbeVariant] = Field(min_length=1)
    question_set_version: str | None = None
    no_cache: bool = False


class RunCreated(Model):
    """A run that has started."""

    id: str


class TargetCounts(Model):
    """One target's job counts in a run."""

    target: str
    jobs: int
    sent: int
    cached: int
    failed: int
    skipped: int
    skip_reason: str | None = None
    """Why the target's jobs were skipped, like `Ollama isn't running`."""


class RunCounts(Model):
    """Job counts for a run. `done` is `sent + cached + failed + skipped`."""

    jobs: int
    done: int
    sent: int
    cached: int
    failed: int
    skipped: int
    targets: list[TargetCounts]


class RunSummary(Model):
    """A run's settings, status, and counts."""

    id: str
    kind: RunKind
    suite: str
    question_set: str
    question_set_version: str
    policy: str | None
    policy_version: str | None
    targets: list[str]
    repeats: int
    variants: list[ProbeVariant]
    """The probe variants. Empty for a suite run."""
    no_cache: bool
    baseline: str | None
    status: RunStatus
    case_count: int
    counts: RunCounts
    cost_usd: float | None
    """The total cost of sent requests. Cached results cost nothing. `None` until a result arrives from the cache or
    from a target whose price is known."""
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: ApiErrorBody | None = None
    """Why the run failed, when `status` is `failed`."""


class RunList(Model):
    """Runs, newest first."""

    runs: list[RunSummary]


# Run events


class ProgressEvent(Model):
    """The run's status and counts. Sent first on every connection, and whenever the status changes."""

    type: Literal["progress"] = "progress"
    run_id: str
    status: RunStatus
    counts: RunCounts


class ResultEvent(Model):
    """One job finished."""

    type: Literal["result"] = "result"
    run_id: str
    case_id: str
    target: str
    repeat: int
    """The repeat index, from 0."""
    variant: str | None = None
    """The probe variant id, like `option_order:2`. `None` for the original case."""
    cached: bool
    result: TargetResult
    """The result, with `request_body` and `raw` set to `null`. Get them from `GET /api/runs/{id}/cases/{case_id}`."""
    counts: RunCounts


class TargetSkippedEvent(Model):
    """A target's jobs were skipped, because it isn't ready or a preflight check failed for every case."""

    type: Literal["target_skipped"] = "target_skipped"
    run_id: str
    target: str
    reason: str
    counts: RunCounts


class FinishedEvent(Model):
    """The run finished. The stream ends after this event."""

    type: Literal["finished"] = "finished"
    run_id: str
    counts: RunCounts
    summary: RunSummary


class CancelledEvent(Model):
    """The run was cancelled. The stream ends after this event."""

    type: Literal["cancelled"] = "cancelled"
    run_id: str
    counts: RunCounts
    summary: RunSummary


class RunErrorEvent(Model):
    """The run failed. The stream ends after this event."""

    type: Literal["error"] = "error"
    run_id: str
    error: ApiErrorBody
    counts: RunCounts
    summary: RunSummary


type RunEvent = Annotated[
    ProgressEvent | ResultEvent | TargetSkippedEvent | FinishedEvent | CancelledEvent | RunErrorEvent,
    Field(discriminator="type"),
]
"""An event in a run's stream. The SSE `event` field is the same as `type`."""


# Metrics


class QuestionMetrics(Model):
    """One target's metrics for one question. A metric that doesn't apply to the question's type is `None`."""

    question: str
    type: QuestionType
    n: int
    """Answers scored against an expectation."""
    accuracy: float | None
    macro_f1: float | None
    """Choice only: F1 averaged across options."""
    mae: float | None
    """Score only: mean absolute error between `score` and the expected level."""
    within_tolerance: float | None
    """Score only: the share of answers whose `level` is within the case's tolerance."""
    brier: float | None
    """Noul only."""
    log_loss: float | None
    """Noul only."""
    auroc: float | None
    """Noul only. `None` when the cases are all yes or all no."""
    ece: float | None
    """Expected calibration error. `None` for a target without probabilities."""
    abstention_rate: float | None
    """Choice only: how often the target chose the question's abstention option. `None` when it has none."""
    consistency: float | None
    """The share of cases whose answer was the same in every repeat. `None` with one repeat."""


class DecisionMetrics(Model):
    """One target's decision metrics, for a suite with a policy."""

    n: int
    """Cases with an expected action."""
    accuracy: float | None
    decided_share: float | None
    """The share of cases the policy decided without escalating."""
    error_rate: float | None
    """The error rate among the cases the policy decided."""
    cost: float | None
    """The total error cost from the policy's cost matrix. `None` when it has none."""


class TargetMetrics(Model):
    """One target's metrics in a run."""

    target: str
    results: int
    errors: int
    skipped: int
    probabilities: bool
    """Whether the target returns probabilities. Calibration metrics are `None` when it doesn't."""
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    cost_usd: float | None
    cost_per_1k_usd: float | None
    """The cost of 1,000 requests at this run's average cost per request."""
    questions: list[QuestionMetrics]
    decision: DecisionMetrics | None
    """`None` when the suite has no policy."""


class RunMetrics(Model):
    """Metrics for each target in a run."""

    run_id: str
    questions: list[str]
    """The question ids, in the question set's order."""
    targets: list[TargetMetrics]


class ConfusionMatrix(Model):
    """Expected options against answered options, for one choice question and one target."""

    run_id: str
    target: str
    question: str
    options: list[str]
    """Row and column labels: the question's options in order, then any unknown options the target answered."""
    counts: list[list[int]]
    """`counts[i][j]` is the number of cases that expected `options[i]` and got `options[j]`."""
    correct: int
    total: int
    recall: list[float | None]
    """Recall for each option. `None` for an option no case expected."""


class CalibrationBin(Model):
    """One probability bin of a reliability table."""

    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    """`None` when the bin is empty."""
    observed_rate: float | None
    """`None` when the bin is empty."""


class Calibration(Model):
    """A reliability table for one question and one target.

    For a noul question the predicted value is the probability of yes. For a choice question it's the probability of
    the chosen option, and the observed rate is how often that choice was correct.
    """

    run_id: str
    target: str
    question: str
    bins: list[CalibrationBin]
    ece: float | None
    n: int


type ChangeStatus = Literal["fixed", "broken", "changed"]
"""`fixed` and `broken` compare each answer with the expectation. `changed` means neither answer was correct, or the
case has no expectation."""


class AnswerChange(Model):
    """A case whose answer changed from the baseline run."""

    case_id: str
    target: str
    question: str
    expected: AnswerValue | None
    baseline_answer: AnswerValue | None
    """`None` when the baseline has no answer."""
    baseline_probability: float | None
    """The probability of the baseline's answer."""
    answer: AnswerValue | None
    probability: float | None
    status: ChangeStatus


class ChangeSummary(Model):
    """One target's changes from the baseline, with McNemar's test on the paired results."""

    target: str
    fixed: int
    broken: int
    changed: int
    mcnemar_p: float | None
    """The exact two-sided p-value. `None` when nothing was fixed or broken."""


class RunChanges(Model):
    """The answers that changed between a run and a baseline run, for the targets both ran."""

    run_id: str
    baseline: str
    changes: list[AnswerChange]
    summary: list[ChangeSummary]


class CaseResult(Model):
    """One job's result for a case."""

    target: str
    repeat: int
    variant: str | None = None
    cached: bool
    correct: dict[str, bool | None]
    """Whether each answer meets the case's expectation, keyed by question id. `None` without an expectation."""
    result: TargetResult


class RunCase(Model):
    """A case in a run, with every target's result."""

    run_id: str
    case: Case
    questions: dict[str, Question]
    """The questions the run asked, so the answers can be labeled."""
    results: list[CaseResult]


class RunReport(Model):
    """The result of `jevtester report`."""

    summary: RunSummary
    metrics: RunMetrics
    markdown: str
    """The same report as Markdown."""


# Probes


class ProbeCell(Model):
    """How often one case's answers changed under one variant on one target."""

    case_id: str
    target: str
    variant: ProbeVariant
    instances: int
    """The variant requests made from the case, like several shuffles of option order."""
    changed: int
    """Instances where any answer differed from the original's."""
    change_rate: float | None


class ProbeSummary(Model):
    """The change rate of one variant on one target, across every case."""

    target: str
    variant: ProbeVariant
    cases: int
    change_rate: float | None


class ProbeReport(Model):
    """A probe run's results."""

    run_id: str
    variants: list[ProbeVariant]
    cells: list[ProbeCell]
    summary: list[ProbeSummary]


# Policies


class PolicyThreshold(Model):
    """A threshold a policy uses, with any per-target values."""

    name: str
    value: float
    per_target: dict[str, float]


class PolicySummary(Model):
    """A policy in the list of policies."""

    name: str
    version: str
    actions: list[str]
    suites: list[str]
    """Suites that use this policy."""


class PolicyList(Model):
    """Every policy under `suites/`."""

    policies: list[PolicySummary]


class PolicyDetail(Model):
    """A policy's YAML text and what it defines."""

    name: str
    version: str
    """The SHA-256 hash of the parsed policy."""
    yaml: str
    actions: list[str]
    thresholds: list[PolicyThreshold]
    suites: list[str]


class PolicyBody(Model):
    """A policy's new YAML text."""

    yaml: str


class SweepBody(Model):
    """A threshold sweep over a finished run's answers."""

    run_id: str
    target: str
    threshold: str
    start: float = 0.0
    stop: float = 1.0
    step: float = Field(default=0.05, gt=0)


class SweepPoint(Model):
    """The policy's outcome at one threshold value."""

    value: float
    decided_share: float | None
    error_rate: float | None
    cost: float | None


class SweepResult(Model):
    """The trade-off between cases decided and errors as a threshold moves."""

    policy: str
    run_id: str
    target: str
    threshold: str
    current: float | None
    """The threshold's value in the policy, for this target."""
    points: list[SweepPoint]


__all__ = [
    "AnswerChange",
    "AnswerValue",
    "ApiError",
    "ApiErrorBody",
    "ApiErrorCode",
    "Calibration",
    "CalibrationBin",
    "CancelledEvent",
    "CaseCreated",
    "CaseResult",
    "ChangeStatus",
    "ChangeSummary",
    "ConfusionMatrix",
    "DecideBody",
    "DecideResponse",
    "DecisionMetrics",
    "DiffStatus",
    "ErrorDetail",
    "FinishedEvent",
    "OptionDiff",
    "PolicyBody",
    "PolicyDetail",
    "PolicyList",
    "PolicySummary",
    "PolicyThreshold",
    "ProbeCell",
    "ProbeCreate",
    "ProbeReport",
    "ProbeSummary",
    "ProbeVariant",
    "ProgressEvent",
    "QuestionDiff",
    "QuestionMetrics",
    "QuestionSetBody",
    "QuestionSetDetail",
    "QuestionSetDiff",
    "QuestionSetList",
    "QuestionSetSummary",
    "QuestionSetVersion",
    "QuestionSetVersions",
    "ResultError",
    "ResultEvent",
    "RunCase",
    "RunChanges",
    "RunCounts",
    "RunCreate",
    "RunCreated",
    "RunErrorEvent",
    "RunEvent",
    "RunKind",
    "RunList",
    "RunMetrics",
    "RunReport",
    "RunStatus",
    "RunSummary",
    "SuiteCheck",
    "SuiteDetail",
    "SuiteList",
    "SuiteSummary",
    "SweepBody",
    "SweepPoint",
    "SweepResult",
    "TargetCounts",
    "TargetInfo",
    "TargetList",
    "TargetMetrics",
    "TargetSkippedEvent",
    "TargetStatus",
    "WordingCheck",
    "WordingCheckCode",
]
