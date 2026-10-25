"""Request and response models for the operations in `service.py`.

The HTTP API returns these models as JSON, and the CLI's `--format json` output uses the same models, so scripts,
agents, and the UI parse one format. `docs/reference/http-api.md` describes them, and `docs/openapi.json` is
generated from them. Each field's docstring is its description in the OpenAPI document.
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
    """What's wrong, for a person."""
    line: int | None = None
    """The line of a YAML document the error is on, from 1, for an editor to mark. `None` when it isn't known."""


class ApiErrorBody(Model):
    """What went wrong."""

    code: ApiErrorCode
    """Why the request failed: `invalid_request` (422), `not_found` (404), `conflict` or `not_ready` (409), or
    `internal` (500)."""
    message: str
    """What went wrong, for a person. For a validation error, it's the first error's message."""
    field: str | None = None
    """The dotted path of the first invalid field, like `questions.intent.choice.criteria`. `null` when the error isn't
    about one field."""
    details: list[ErrorDetail] = Field(default_factory=list[ErrorDetail])
    """Every validation error, for a form or editor that shows them all. An error about one field lists that field here
    too. Empty for an error that isn't about a field."""


class ApiError(Model):
    """The body of every 4xx and 5xx response."""

    error: ApiErrorBody
    """What went wrong."""


# Targets


type TargetStatus = Literal["ready", "warning", "down", "unchecked"]
"""`down` when the last health check gave a reason, `warning` when the target is ready and has warnings, `ready`
otherwise, and `unchecked` before the first health check."""


class TargetInfo(Model):
    """A target, its capabilities, and its last health check."""

    name: str
    """The target's id, like `decision-1@foundry`. Pass it in a request's `targets`."""
    label: str
    """The name people read, like `Microsoft-Decision-1, Azure Foundry`."""
    provider: ProviderName
    """The provider that sends the target its requests: `systemone` for System One servers (Foundry, Ollama, and the MLX
    server), `workers-ai` for Cloudflare Workers AI, or `claude`, which isn't built yet."""
    model: str
    """The model name sent in each request. On Foundry it's the deployment name."""
    base_url: str | None
    """The API root of the target's server. `null` for a target with no `base_url` in the config, like a Workers AI
    target."""
    local: bool
    """Whether the target runs on this machine: its `base_url` host is `localhost`, `127.0.0.1`, or `::1`. It doesn't
    affect cost, which comes from the target's `input_cost_per_mtok_usd`."""
    status: TargetStatus
    """The target's state after its last health check: `ready`, `warning` (ready, with `warnings`), `down` (see
    `reason`), or `unchecked` (no health check has run since the server started)."""
    reason: str | None = None
    """Why the target is down, like `Ollama isn't running`. `null` unless `status` is `down`."""
    detail: str | None = None
    """What to do about it, or more about the target's state, like `Needs 0.35.1 or later`. `null` when the health check
    has nothing to add."""
    credential: str | None = None
    """Where the credential comes from and when it expires, like `Azure CLI, refreshes in 41 min`. `null` for a target
    without a credential, or before a health check."""
    warnings: list[ResultWarning] = Field(default_factory=list[ResultWarning])
    """Warnings that apply to every request, from the target's config: `state_may_truncate` when
    `capabilities.truncates_state` is true, and `truncation_on` when the target sets `truncate = true`."""
    checked_at: datetime | None = None
    """When the target's last health check ran. `null` before the first one."""
    capabilities: Capabilities
    """What the target accepts and returns, from the config."""


class TargetList(Model):
    """Every configured target."""

    targets: list[TargetInfo]
    """Every target, in the config's order."""
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
    """The state and questions as sent, so a client can label every result from the response alone."""
    question_set_version: str
    """The hash of the request's questions, as a question set with them would have."""
    asked_at: datetime
    """When jevtester sent the request."""
    results: list[TargetResult]
    """One result per target, in the order the targets were named. A target that failed has `ok: false` and an
    `error`."""


# Suites and cases


class SuiteSummary(Model):
    """A suite in the list of suites."""

    name: str
    """The suite's name: its file name in `suites/`, without `.yaml`."""
    question_set: str
    """The name of the question set the suite asks."""
    question_set_version: str | None
    """The current version of the suite's question set. `None` when the question set doesn't exist."""
    policy: str | None
    """The name of the suite's policy. `null` when it has none."""
    targets: list[str]
    """The targets a run of the suite uses when the run names none. Empty means the config's default targets."""
    case_count: int
    """Cases that count in evaluation. Claude drafts aren't included."""
    draft_count: int
    """Cases with `provenance: "claude-draft"`."""


class SuiteList(Model):
    """Every suite under `suites/`."""

    suites: list[SuiteSummary]
    """Every suite, by name."""


class SuiteDetail(Model):
    """A suite with its cases and its question set."""

    suite: Suite
    """The suite as its file has it, with every case."""
    question_set: QuestionSet
    """The suite's question set as its file has it now, with its `version`."""


class CaseCreated(Model):
    """A case saved to a suite."""

    suite: str
    """The suite's name."""
    case: Case
    """The case as saved."""
    case_count: int
    """The suite's case count after the save. Claude drafts aren't included."""


type WordingCheckCode = Literal[
    "multiple_dimensions", "degree_words", "bare_number_levels", "no_abstention", "duplicate_options"
]
"""Which of the vendors' question-writing rules a question may break."""


class WordingCheck(Model):
    """A finding from the question-wording checks."""

    question: str
    """The id of the question the finding is about."""
    code: WordingCheckCode
    """Which check found it: `multiple_dimensions` (more than one question mark), `degree_words` (criteria with words
    like "very" or "somewhat"), `bare_number_levels` (score levels that are only numbers), `no_abstention` (a choice
    with no option like `cannot_tell`), or `duplicate_options`."""
    message: str
    """What the check found, for a person."""


class SuiteCheck(Model):
    """The result of `jevtester suite check`."""

    suite: str
    """The suite's name."""
    valid: bool
    """Whether the suite, its question set, and its policy load, and every case's expectations name real questions."""
    errors: list[ErrorDetail]
    """Every problem that makes the suite invalid. Empty when `valid` is true."""
    checks: list[WordingCheck]
    """Question-wording findings. Each is a prompt to look at a question, and none makes the suite invalid."""


# Question sets


class QuestionSetSummary(Model):
    """A question set in the list of question sets."""

    name: str
    """The question set's name: its file name in `suites/question-sets/`, without `.yaml`."""
    version: str
    """The current version: the SHA-256 hash of the questions."""
    question_count: int
    """The number of questions in the current version."""
    suites: list[str]
    """Suites that use this question set."""
    updated_at: datetime | None
    """When the current version was first seen."""


class QuestionSetList(Model):
    """Every question set under `suites/`."""

    question_sets: list[QuestionSetSummary]
    """Every question set, by name."""


class QuestionSetDetail(Model):
    """A question set's current version, the suites that use it, and its wording checks."""

    question_set: QuestionSet
    """The question set as its file has it now, with its `version`."""
    suites: list[str]
    """Suites that use this question set."""
    checks: list[WordingCheck]
    """Question-wording findings for the questions."""


class QuestionSetBody(Model):
    """The questions to save as a question set's new version."""

    questions: dict[str, Question] = Field(min_length=1)
    """The questions, keyed by the id each answer comes back under. They replace every question in the set."""


class QuestionSetVersion(Model):
    """One version of a question set."""

    version: str
    """The version's SHA-256 hash."""
    first_seen: datetime
    """When jevtester first saw this version: when a suite or question set was read or saved, or when a run used it."""
    question_count: int
    """The number of questions in this version."""
    run_count: int
    """Runs that used this version."""
    current: bool
    """Whether this is the version in the YAML file now."""


class QuestionSetVersions(Model):
    """A question set's versions, newest first."""

    name: str
    """The question set's name."""
    versions: list[QuestionSetVersion]
    """Every version jevtester has seen, newest first."""


type DiffStatus = Literal["added", "removed", "changed", "unchanged"]


class OptionDiff(Model):
    """How one option or level changed."""

    key: str
    """The option name for a choice, or the level index for a score."""
    status: DiffStatus
    before: str | None
    """The option's description, or the level's text, in the older version. `null` when it was added."""
    after: str | None
    """The option's description, or the level's text, in the newer version. `null` when it was removed."""


class QuestionDiff(Model):
    """How one question changed between two versions."""

    id: str
    """The question's id."""
    status: DiffStatus
    before: Question | None
    """The question in the older version. `null` when it was added."""
    after: Question | None
    """The question in the newer version. `null` when it was removed."""
    changed_fields: list[Literal["type", "instructions", "criteria"]]
    """The question's fields that differ between the versions."""
    options: list[OptionDiff]
    """Options or levels in the newer version's order, then removed ones."""
    order_changed: bool
    """Whether the options that both versions have are in a different order."""


class QuestionSetDiff(Model):
    """The differences between two versions of a question set."""

    name: str
    """The question set's name."""
    from_version: str
    """The older version's full hash."""
    to_version: str
    """The newer version's full hash."""
    questions: list[QuestionDiff]
    """How each question changed."""


# Runs


type RunKind = Literal["suite", "probe"]
type RunStatus = Literal["queued", "running", "finished", "cancelled", "failed"]
type ProbeVariant = Literal["option_order", "key_order", "bare_levels", "pad_state"]


class RunCreate(Model):
    """A run to start."""

    suite: str
    """The suite's name."""
    targets: list[str] = Field(default_factory=list[str])
    """Target names. Empty means the suite's default targets, or else the config's."""
    question_set_version: str | None = None
    """A question set version to run, as its hash or a prefix of 8 or more characters. `null` runs the current
    version."""
    repeats: int | None = Field(default=None, ge=1)
    """Times to send each request. `None` uses the config's default."""
    no_cache: bool = False
    """Send every request, even when a cached result exists."""
    baseline: str | None = None
    """A run to compare with. It must exist. A report of this run then includes the answers that changed from the
    baseline."""


class ProbeCreate(Model):
    """A probe run to start."""

    suite: str
    """The suite's name."""
    targets: list[str] = Field(default_factory=list[str])
    """Target names. Empty means the suite's default targets, or else the config's."""
    variants: list[ProbeVariant] = Field(min_length=1)
    """The probes to run: `option_order`, `key_order`, `bare_levels`, or `pad_state`. A probe named twice runs once."""
    question_set_version: str | None = None
    """A question set version to run, as its hash or a prefix of 8 or more characters. `null` runs the current
    version."""
    no_cache: bool = False
    """Send every request, even when a cached result exists."""


class RunCreated(Model):
    """A run that has started."""

    id: str
    """The run's id, like `0002`. Pass it to `GET /api/runs/{id}/events` to follow the run."""


class TargetCounts(Model):
    """One target's job counts in a run."""

    target: str
    """The target's name."""
    jobs: int
    """Jobs for this target."""
    sent: int
    """Jobs sent that got an answer."""
    cached: int
    """Jobs answered from the cache."""
    failed: int
    """Jobs sent that failed."""
    skipped: int
    """Jobs skipped because the target was down when the run started."""
    skip_reason: str | None = None
    """Why the target's jobs were skipped, like `Ollama isn't running`."""


class RunCounts(Model):
    """Job counts for a run. `done` is `sent + cached + failed + skipped`."""

    jobs: int
    """Jobs in the run. A job is one case on one target for one repeat, or for one probe variant."""
    done: int
    """Jobs finished. `done / jobs` is the run's progress."""
    sent: int
    """Jobs sent that got an answer."""
    cached: int
    """Jobs answered from the cache."""
    failed: int
    """Jobs sent that failed."""
    skipped: int
    """Jobs skipped because their target was down when the run started."""
    targets: list[TargetCounts]
    """The counts for each target, in the run's target order."""


class RunSummary(Model):
    """A run's settings, status, and counts."""

    id: str
    """The run's id: four or more digits, like `0002`, counting up from `0001`."""
    kind: RunKind
    """`suite` for a suite run, or `probe` for a probe run."""
    suite: str
    """The suite's name."""
    question_set: str
    """The question set's name."""
    question_set_version: str
    """The full hash of the question set version the run asked."""
    policy: str | None
    """The suite's policy when the run started. `null` when it has none."""
    policy_version: str | None
    """The hash of the policy as it was when the run started. `null` without a policy."""
    targets: list[str]
    """The targets the run used, in order."""
    repeats: int
    """Times each case was sent to each target. Always 1 for a probe run."""
    variants: list[ProbeVariant]
    """The probe variants. Empty for a suite run."""
    no_cache: bool
    """Whether the run sent every request, even when a cached result existed."""
    baseline: str | None
    """The run to compare with. `null` when the run has none."""
    status: RunStatus
    """`queued`, then `running`, then `finished`, `cancelled`, or `failed`. A run that was running when the server
    stopped becomes `failed`."""
    case_count: int
    """Cases the run sent. Claude drafts aren't included."""
    counts: RunCounts
    """Job counts, as they stand now."""
    cost_usd: float | None
    """The total cost of sent requests. Cached results cost nothing. `None` until a result arrives from the cache or
    from a target whose price is known."""
    created_at: datetime
    """When the run was queued."""
    started_at: datetime | None
    """When the run started sending. `null` while it's queued."""
    finished_at: datetime | None
    """When the run ended. `null` until it does."""
    error: ApiErrorBody | None = None
    """Why the run failed, when `status` is `failed`."""


class RunList(Model):
    """Runs, newest first."""

    runs: list[RunSummary]
    """Every run, newest first."""


# Run events


class ProgressEvent(Model):
    """The run's status and counts. Sent first on every connection, and whenever the status changes."""

    type: Literal["progress"] = "progress"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    status: RunStatus
    """The run's status."""
    counts: RunCounts
    """The run's counts."""


class ResultEvent(Model):
    """One job finished."""

    type: Literal["result"] = "result"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    case_id: str
    """The case's id."""
    target: str
    """The target's name."""
    repeat: int
    """The repeat index, from 0."""
    variant: str | None = None
    """The probe variant id, like `option_order:2`. `None` for the original case."""
    cached: bool
    """Whether the result came from the cache."""
    result: TargetResult
    """The result, with `request_body` and `raw` set to `null`. Get them from `GET /api/runs/{id}/cases/{case_id}`."""
    counts: RunCounts
    """The run's counts after this job."""


class TargetSkippedEvent(Model):
    """A target's jobs were skipped, because its health check failed when the run started."""

    type: Literal["target_skipped"] = "target_skipped"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    target: str
    """The target's name."""
    reason: str
    """Why the jobs were skipped, like `Ollama isn't running`."""
    counts: RunCounts
    """The run's counts after the skip."""


class FinishedEvent(Model):
    """The run finished. The stream ends after this event."""

    type: Literal["finished"] = "finished"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    counts: RunCounts
    """The run's final counts."""
    summary: RunSummary
    """The run's final summary."""


class CancelledEvent(Model):
    """The run was cancelled. The stream ends after this event."""

    type: Literal["cancelled"] = "cancelled"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    counts: RunCounts
    """The run's counts when it was cancelled."""
    summary: RunSummary
    """The run's final summary."""


class RunErrorEvent(Model):
    """The run failed. The stream ends after this event."""

    type: Literal["error"] = "error"
    """The event type. It matches the SSE `event` field."""
    run_id: str
    """The run's id."""
    error: ApiErrorBody
    """Why the run failed."""
    counts: RunCounts
    """The run's counts when it failed."""
    summary: RunSummary
    """The run's final summary."""


type RunEvent = Annotated[
    ProgressEvent | ResultEvent | TargetSkippedEvent | FinishedEvent | CancelledEvent | RunErrorEvent,
    Field(discriminator="type"),
]
"""An event in a run's stream. The SSE `event` field is the same as `type`."""


# Metrics


class QuestionMetrics(Model):
    """One target's metrics for one question. A metric that doesn't apply to the question's type is `None`."""

    question: str
    """The question's id."""
    type: QuestionType
    """The question's type."""
    n: int
    """Answers scored against an expectation."""
    accuracy: float | None
    """The share of scored answers that match the expected answer, or one of the `acceptable` ones. For a score, only
    the exact level counts. A missing answer is wrong."""
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
    """The target's name."""
    results: int
    """Results for the original cases, failed ones included. Probe variants aren't counted."""
    errors: int
    """Results that failed."""
    skipped: int
    """Jobs skipped because the target was down when the run started."""
    probabilities: bool
    """Whether the target returns probabilities. Calibration metrics are `None` when it doesn't."""
    latency_p50_ms: float | None
    """The median latency of successful results, in milliseconds. `null` without one."""
    latency_p95_ms: float | None
    """The 95th percentile latency of successful results, in milliseconds. `null` without one."""
    cost_usd: float | None
    """The cost of the requests the run sent. `0` when every result came from the cache. `null` when the target's price
    is unknown."""
    cost_per_1k_usd: float | None
    """The cost of 1,000 requests at this run's average cost per request."""
    questions: list[QuestionMetrics]
    """Metrics for each question, in the question set's order. Empty when the target has no results."""
    decision: DecisionMetrics | None
    """`None` when the suite has no policy."""


class RunMetrics(Model):
    """Metrics for each target in a run."""

    run_id: str
    """The run's id."""
    questions: list[str]
    """The question ids, in the question set's order."""
    targets: list[TargetMetrics]
    """Metrics for each target, in the run's target order."""


class ConfusionMatrix(Model):
    """Expected options against answered options, for one choice question and one target."""

    run_id: str
    """The run's id."""
    target: str
    """The target's name."""
    question: str
    """The choice question's id."""
    options: list[str]
    """Row and column labels: the question's options in order, then any unknown options the target answered."""
    counts: list[list[int]]
    """`counts[i][j]` is the number of cases that expected `options[i]` and got `options[j]`."""
    correct: int
    """Cases where the target chose the expected option: the sum of the diagonal."""
    total: int
    """Cases counted: those that expect an option and have the target's choice."""
    recall: list[float | None]
    """Recall for each option. `None` for an option no case expected."""


class CalibrationBin(Model):
    """One probability bin of a reliability table."""

    lower: float
    """The bin's lowest predicted probability."""
    upper: float
    """The bin's highest predicted probability."""
    count: int
    """Predictions in the bin."""
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
    """The run's id."""
    target: str
    """The target's name."""
    question: str
    """The question's id."""
    bins: list[CalibrationBin]
    """Equal-width bins from 0 to 1, lowest first."""
    ece: float | None
    """Expected calibration error: the count-weighted mean gap between each bin's mean prediction and its observed rate.
    `null` when there are no predictions."""
    n: int
    """Predictions counted."""


type ChangeStatus = Literal["fixed", "broken", "changed"]
"""`fixed` went from wrong to right and `broken` from right to wrong. `changed` stayed right or stayed wrong, for
example a score that moved within its tolerance, or the case has no expectation."""


class AnswerChange(Model):
    """A case whose answer changed from the baseline run."""

    case_id: str
    """The case's id."""
    target: str
    """The target's name."""
    question: str
    """The question's id."""
    expected: AnswerValue | None
    """The case's expected answer. `null` when the case expects none."""
    baseline_answer: AnswerValue | None
    """`None` when the baseline has no answer."""
    baseline_probability: float | None
    """The probability of the baseline's answer."""
    answer: AnswerValue | None
    """The answer in this run. `null` when there's none."""
    probability: float | None
    """The probability of this run's answer."""
    status: ChangeStatus
    """`fixed` went from wrong to right, and `broken` from right to wrong. `changed` stayed right or stayed wrong, like
    a score that moved within its tolerance, or the case has no expectation."""


class ChangeSummary(Model):
    """One target's changes from the baseline, with McNemar's test on the paired results."""

    target: str
    """The target's name."""
    fixed: int
    """Answers that went from wrong to right."""
    broken: int
    """Answers that went from right to wrong."""
    changed: int
    """Answers that changed and stayed right or stayed wrong."""
    mcnemar_p: float | None
    """The exact two-sided p-value. `None` when nothing was fixed or broken."""


class RunChanges(Model):
    """The answers that changed between a run and a baseline run, for the targets both ran."""

    run_id: str
    """The run's id."""
    baseline: str
    """The baseline run's id."""
    changes: list[AnswerChange]
    """Each answer that changed, on the first repeat of each case."""
    summary: list[ChangeSummary]
    """One row for each target both runs ran."""


class Regression(Model):
    """A metric that dropped by more than the allowed amount from the baseline."""

    target: str
    """The target's name."""
    question: str
    """The question's id."""
    metric: Literal["accuracy", "within_tolerance"]
    """`within_tolerance` for a score question, or `accuracy` for any other."""
    baseline: float
    """The metric in the baseline run."""
    value: float
    """The metric in this run."""
    drop: float
    """`baseline - value`."""


class RunComparison(Model):
    """The result of `jevtester compare`: both runs' metrics, the changed answers, and any regressions."""

    run_metrics: RunMetrics
    """This run's metrics."""
    baseline_metrics: RunMetrics
    """The baseline run's metrics."""
    changes: RunChanges
    """The answers that changed from the baseline."""
    max_drop: float
    """The largest drop allowed in accuracy, or in within-tolerance accuracy for a score question."""
    regressions: list[Regression]
    """Each target and question whose metric dropped by more than `max_drop`. Empty when none did."""


type BandLevel = Literal["act", "confirm", "escalate"]


class PolicyDecision(Model):
    """The action a policy chose from one result's answers."""

    action: str
    """The action, like `parley_succeeds`."""
    band: BandLevel
    """The lowest band among the policy's banded questions: `act` when every one is at its `act` value or above,
    `confirm` when one is between `confirm` and `act`, and `escalate` below that. `act` when the policy has no
    bands."""
    escalated: bool
    """Whether the policy escalated instead of deciding, because of a band. A rule may still choose `escalate` as
    an action."""
    rule: int | None
    """The index of the rule that chose the action. `None` for the default action or a band escalation."""
    composites: dict[str, float | None]
    """Each composite's value. `None` when an answer it needs is missing."""
    reason: str | None = None
    """Why the policy escalated, or that no rule matched."""


class CaseResult(Model):
    """One job's result for a case."""

    target: str
    """The target's name."""
    repeat: int
    """The repeat index, from 0."""
    variant: str | None = None
    """The probe variant id, like `option_order:2`. `null` for the original case."""
    cached: bool
    """Whether the result came from the cache."""
    correct: dict[str, bool | None]
    """Whether each answer meets the case's expectation, keyed by question id. `None` without an expectation."""
    decision: PolicyDecision | None = None
    """The suite policy's decision from these answers. `None` without a policy, or when the target failed."""
    result: TargetResult
    """The full result, with `request_body` and `raw`."""


class RunCase(Model):
    """A case in a run, with every target's result."""

    run_id: str
    """The run's id."""
    case: Case
    """The case as the run sent it. Editing the suite later doesn't change it."""
    questions: dict[str, Question]
    """The questions the run asked, so the answers can be labeled."""
    results: list[CaseResult]
    """Every job's result for the case: each target, repeat, and probe variant."""


class RunReport(Model):
    """The result of `jevtester report`."""

    summary: RunSummary
    """The run's summary."""
    metrics: RunMetrics
    """The run's metrics."""
    markdown: str
    """The same report as Markdown."""


# Probes


class ProbeCell(Model):
    """How often one case's answers changed under one variant on one target."""

    case_id: str
    """The case's id."""
    target: str
    """The target's name."""
    variant: ProbeVariant
    """The probe."""
    instances: int
    """Variant requests made from the case that got an answer, like several shuffles of option order. A failed request
    isn't counted."""
    changed: int
    """Instances where any answer differed from the original's."""
    change_rate: float | None
    """`changed / instances`."""


class ProbeSummary(Model):
    """The change rate of one variant on one target, across every case."""

    target: str
    """The target's name."""
    variant: ProbeVariant
    """The probe."""
    cases: int
    """Cases with at least one instance of the probe."""
    change_rate: float | None
    """Changed instances divided by all instances, across every case. `null` when the probe made no instances on this
    target."""


class ProbeReport(Model):
    """A probe run's results."""

    run_id: str
    """The probe run's id."""
    variants: list[ProbeVariant]
    """The probes the run made."""
    cells: list[ProbeCell]
    """One cell for each case, target, and probe that has instances."""
    summary: list[ProbeSummary]
    """One row for each target and probe."""


# Policies


class PolicyThreshold(Model):
    """A threshold a policy uses, with any per-target values."""

    name: str
    """The threshold's name."""
    value: float
    """The shared value."""
    per_target: dict[str, float]
    """Values for single targets, keyed by target name. They replace the shared value for that target."""


class PolicySummary(Model):
    """A policy in the list of policies."""

    name: str
    """The policy's name: its file name in `suites/policies/`, without `.yaml`."""
    version: str
    """The SHA-256 hash of the parsed policy. Comments and layout aren't part of it."""
    actions: list[str]
    """Every action the policy can choose, in the order it names them."""
    suites: list[str]
    """Suites that use this policy."""


class PolicyList(Model):
    """Every policy under `suites/`."""

    policies: list[PolicySummary]
    """Every policy, by name."""


class PolicyDetail(Model):
    """A policy's YAML text and what it defines."""

    name: str
    """The policy's name."""
    version: str
    """The SHA-256 hash of the parsed policy. Comments and layout aren't part of it."""
    yaml: str
    """The policy file's text, comments included."""
    actions: list[str]
    """Every action the policy can choose, in the order it names them."""
    thresholds: list[PolicyThreshold]
    """The policy's thresholds, in the file's order."""
    suites: list[str]
    """Suites that use this policy."""


class PolicyBody(Model):
    """A policy's new YAML text."""

    yaml: str
    """The policy's YAML text. Its `name` must match the policy's name in the path. It's saved as sent, comments
    included, once it validates."""


class SweepBody(Model):
    """A threshold sweep over a finished run's answers."""

    run_id: str
    """The id of the run whose answers the sweep measures."""
    target: str
    """A target the run ran."""
    threshold: str
    """The name of the policy threshold to move."""
    start: float = 0.0
    """The first value."""
    stop: float = 1.0
    """The last value. The sweep includes it when `start` plus a whole number of steps reaches it."""
    step: float = Field(default=0.05, gt=0)
    """The gap between values. A sweep has at most 1,000 points."""


class SweepPoint(Model):
    """The policy's outcome at one threshold value."""

    value: float
    """The threshold's value."""
    decided_share: float | None
    """The share of cases the policy decided without escalating."""
    error_rate: float | None
    """The error rate among the cases the policy decided."""
    cost: float | None
    """The total error cost from the policy's cost matrix. `null` when the policy has no `costs`."""


class SweepResult(Model):
    """The trade-off between cases decided and errors as a threshold moves."""

    policy: str
    """The policy's name."""
    run_id: str
    """The run's id."""
    target: str
    """The target's name."""
    threshold: str
    """The threshold's name."""
    current: float | None
    """The threshold's value in the policy, for this target."""
    points: list[SweepPoint]
    """One point for each value, from `start` up to `stop`."""


__all__ = [
    "AnswerChange",
    "AnswerValue",
    "ApiError",
    "ApiErrorBody",
    "ApiErrorCode",
    "BandLevel",
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
    "PolicyDecision",
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
    "Regression",
    "ResultError",
    "ResultEvent",
    "RunCase",
    "RunChanges",
    "RunComparison",
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
