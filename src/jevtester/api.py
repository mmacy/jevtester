"""The jevtester HTTP API.

Every route calls `service.py`. The routes, their models, and `docs/openapi.json` are the contract, and
`tests/fixtures/api/` has a saved response for each one.
"""

import json
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import TypeAdapter
from starlette.exceptions import HTTPException

from jevtester import __version__
from jevtester.errors import ServiceError
from jevtester.schemas import (
    ApiError,
    ApiErrorBody,
    ApiErrorCode,
    Calibration,
    CaseCreated,
    ConfusionMatrix,
    DecideBody,
    DecideResponse,
    ErrorDetail,
    PolicyBody,
    PolicyDetail,
    PolicyList,
    ProbeCreate,
    ProbeReport,
    QuestionSetBody,
    QuestionSetDetail,
    QuestionSetDiff,
    QuestionSetList,
    QuestionSetVersions,
    RunCase,
    RunChanges,
    RunComparison,
    RunCreate,
    RunCreated,
    RunEvent,
    RunList,
    RunMetrics,
    RunReport,
    RunSummary,
    SuiteCheck,
    SuiteDetail,
    SuiteList,
    SweepBody,
    SweepResult,
    TargetList,
)
from jevtester.service import Service
from jevtester.spec import Case, QuestionSet

HOST = "127.0.0.1"
PORT = 8640
DEV_ORIGINS = ["http://127.0.0.1:5173"]
"""The Vite dev server, which calls the API from another origin while the UI is in development."""

STATIC = Path(__file__).resolve().parent / "static"
"""The built web UI. The frontend build writes it, and git ignores it."""

_STATUS_CODES: dict[int, ApiErrorCode] = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "invalid_request",
}

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {
        "model": ApiError,
        "description": (
            "`not_found`: no route, suite, question set, version, run, case, or policy has that name. Check the name. "
            "A retry with the same name fails the same way."
        ),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ApiError,
        "description": (
            "`invalid_request`: the body, a parameter, or a file it reads is invalid. `details` lists every error, and "
            "`field` is the first one's path. Fix the input before you retry."
        ),
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ApiError,
        "description": "`internal`: a bug in jevtester. `message` says what failed.",
    },
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {
        "model": ApiError,
        "description": "`conflict`: the suite already has a case with this `id`. Choose another id.",
    }
}

_NAME_RULE = "Lowercase letters, digits, `-`, and `_`, up to 64 characters. Any other name returns 422."
type SuiteName = Annotated[str, PathParam(description=f"The suite's name, like `parley`. {_NAME_RULE}")]
type QuestionSetName = Annotated[str, PathParam(description=f"The question set's name, like `parley`. {_NAME_RULE}")]
type PolicyName = Annotated[str, PathParam(description=f"The policy's name, like `parley`. {_NAME_RULE}")]
type RunId = Annotated[
    str,
    PathParam(description="The run's id, like `0002`, from `POST /api/runs`, `POST /api/probes`, or `GET /api/runs`."),
]
type QuestionId = Annotated[str, Query(description="The id of a question the run asked, like `intent`.")]
type TargetName = Annotated[str, Query(description="A target the run ran, like `decision-1@foundry`.")]
type BaselineId = Annotated[str, Query(description="The baseline run's id, like `0001`.")]


class ApiException(Exception):
    """An error a route returns as an [`ApiError`][jevtester.schemas.ApiError] body."""

    def __init__(self, status_code: int, code: ApiErrorCode, message: str, *, field: str | None = None) -> None:
        """Describe the error.

        Args:
            status_code: The HTTP status.
            code: The error code.
            message: What went wrong, for a person.
            field: The dotted path of the invalid field, when there is one.
        """
        super().__init__(message)
        self.status_code = status_code
        self.body = ApiErrorBody(code=code, message=message, field=field)


def _error_response(status_code: int, body: ApiErrorBody) -> JSONResponse:
    return JSONResponse(ApiError(error=body).model_dump(mode="json"), status_code=status_code)


def _field_path(location: Sequence[int | str]) -> str | None:
    # FastAPI prefixes each location with where the value came from: body, query, or path.
    parts = [str(part) for part in location[1:]]
    return ".".join(parts) if parts else None


async def _handle_api_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiException)
    return _error_response(exc.status_code, exc.body)


_SERVICE_STATUS: dict[ApiErrorCode, int] = {
    "invalid_request": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "not_found": status.HTTP_404_NOT_FOUND,
    "conflict": status.HTTP_409_CONFLICT,
    "not_ready": status.HTTP_409_CONFLICT,
    "internal": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


async def _handle_service_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ServiceError)
    # An error about one field lists it in details too, so a form shows every such error the same way.
    details = exc.details or ([ErrorDetail(field=exc.field, message=str(exc))] if exc.field is not None else [])
    body = ApiErrorBody(code=exc.code, message=str(exc), field=exc.field, details=details)
    return _error_response(_SERVICE_STATUS[exc.code], body)


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code = _STATUS_CODES.get(exc.status_code, "internal")
    return _error_response(exc.status_code, ApiErrorBody(code=code, message=str(exc.detail)))


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [ErrorDetail(field=_field_path(error["loc"]), message=error["msg"]) for error in exc.errors()]
    first = details[0] if details else ErrorDetail(message="The request is invalid.")
    body = ApiErrorBody(code="invalid_request", message=first.message, field=first.field, details=details)
    return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, body)


def parse_sse(text: str) -> list[ServerSentEvent]:
    """Split a saved event stream into its events.

    Args:
        text: An event stream in the SSE wire format, with one `data:` line per event.

    Returns:
        The events, in order.
    """
    events: list[ServerSentEvent] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "data" in fields:
            events.append(ServerSentEvent(event=fields.get("event"), id=fields.get("id"), raw_data=fields["data"]))
    return events


class _ServiceHolder:
    """The app's service, loaded from the config on first use."""

    def __init__(self, service: Service | None) -> None:
        self._service = service

    def get(self) -> Service:
        if self._service is None:
            self._service = Service.load()
        return self._service


def _service(request: Request) -> Service:
    holder = cast(_ServiceHolder, request.app.state.service)
    return holder.get()


type ServiceDep = Annotated[Service, Depends(_service)]


def _run(id: RunId, service: ServiceDep) -> RunSummary:
    # A dependency, so an unknown run is a 404 before the event stream starts.
    return service.get_run(id)


type RunDep = Annotated[RunSummary, Depends(_run)]


async def _numbered[T](items: AsyncIterator[T]) -> AsyncIterator[tuple[int, T]]:
    index = 0
    async for item in items:
        yield index, item
        index += 1


router = APIRouter(prefix="/api", responses=_ERRORS)


@router.get(
    "/targets", tags=["targets"], summary="List targets", response_description="Every target, in the config's order."
)
async def list_targets(service: ServiceDep) -> TargetList:
    """List the configured targets with their capabilities and their last health check.

    This call doesn't run a health check, so a target is `unchecked` until `POST /api/targets/check` or a run checks
    it. The server keeps health check results in memory, so they reset when it restarts.
    """
    return service.list_targets()


@router.post(
    "/targets/check",
    tags=["targets"],
    summary="Check targets",
    response_description="Every target, with its new health check result.",
)
async def check_targets(service: ServiceDep) -> TargetList:
    """Run every target's health check at once and return the targets with the results.

    A health check doesn't send a decision request. Foundry needs a token from the `az` sign-in. Ollama must be 0.35.1
    or later and have the model pulled. The MLX server must have the target's model loaded. Workers AI needs a token
    and `cloudflare.account_id`, and its catalog must list the model. A check that takes longer than 15 seconds marks
    the target down.

    After a check, `POST /api/decide` returns `not_ready` for a target that's down instead of sending to it.
    """
    return await service.check_targets()


@router.post(
    "/decide",
    tags=["decide"],
    summary="Ask targets one request",
    response_description="One result per target, in the order the targets were named.",
)
async def decide(body: DecideBody, service: ServiceDep) -> DecideResponse:
    """Send one state and its questions to each chosen target at once, and return one result per target.

    The response arrives when the last target finishes. To show each target's answers as they arrive, send one
    request per target. Name targets in `targets`, or leave it empty for the config's `defaults.targets`. Pass
    `["all"]` for every target. To keep a result as a test case, send its state and answers to
    `POST /api/suites/{name}/cases`.

    A target that fails isn't an HTTP error. Its result has `ok: false` and an `error`, and the other targets' results
    still arrive. A target that's down after its last health check, or a request that fails the target's preflight
    check, gets a result with the error code `not_ready` or `preflight`, and nothing is sent to it. An unknown target
    name, or a name given twice, returns 422 with the field `targets.<index>`.
    """
    return await service.decide(body)


@router.get(
    "/suites", tags=["suites"], summary="List suites", response_description="Every suite under `suites/`, by name."
)
async def list_suites(service: ServiceDep) -> SuiteList:
    """List the suites under `suites/`, with each suite's question set version and case counts.

    An invalid suite file returns 422, which names the file.
    """
    return service.list_suites()


@router.get(
    "/suites/{name}",
    tags=["suites"],
    summary="Get a suite",
    response_description="The suite and its question set.",
)
async def get_suite(name: SuiteName, service: ServiceDep) -> SuiteDetail:
    """Return a suite with its cases and its question set's current version.

    Reading a suite records its question set's version, if jevtester hasn't seen it before. A missing suite or
    question set returns 404, and an invalid file returns 422.
    """
    return service.get_suite(name)


@router.get(
    "/suites/{name}/check",
    tags=["suites"],
    summary="Check a suite",
    response_description="Whether the suite is valid, its errors, and the wording findings.",
)
async def check_suite(name: SuiteName, service: ServiceDep) -> SuiteCheck:
    """Validate a suite and run the question-wording checks on its question set.

    The suite is valid when it, its question set, and its policy load, every case's expectations fit the questions,
    and the policy reads only questions the question set asks. An invalid suite returns 200 with `valid: false` and
    its `errors`. A suite that doesn't exist returns 404.
    """
    return service.check_suite(name)


@router.post(
    "/suites/{name}/cases",
    status_code=status.HTTP_201_CREATED,
    tags=["suites"],
    responses=_CONFLICT,
    summary="Add a case",
    response_description="The saved case and the suite's new case count.",
)
async def add_case(name: SuiteName, case: Case, service: ServiceDep) -> CaseCreated:
    """Add a case to the end of a suite's YAML file.

    jevtester rewrites the file from its parsed contents, so the change shows up in `git diff` and comments in the file
    are lost. A case id the suite already has returns 409, and nothing is saved.
    """
    return service.add_case(name, case)


@router.get(
    "/question-sets",
    tags=["question sets"],
    summary="List question sets",
    response_description="Every question set under `suites/question-sets/`, by name.",
)
async def list_question_sets(service: ServiceDep) -> QuestionSetList:
    """List the question sets under `suites/question-sets/`.

    Each has its current version and the suites that use it.
    """
    return service.list_question_sets()


@router.get(
    "/question-sets/{name}",
    tags=["question sets"],
    summary="Get a question set",
    response_description="The question set, the suites that use it, and its wording findings.",
)
async def get_question_set(name: QuestionSetName, service: ServiceDep) -> QuestionSetDetail:
    """Return a question set's current version, the suites that use it, and its wording checks."""
    return service.get_question_set(name)


@router.put(
    "/question-sets/{name}",
    tags=["question sets"],
    summary="Save a question set",
    response_description="The saved question set, with its new version.",
)
async def save_question_set(name: QuestionSetName, body: QuestionSetBody, service: ServiceDep) -> QuestionSetDetail:
    """Replace a question set's questions, which makes a new version. Creates the question set if it's new.

    jevtester rewrites `suites/question-sets/<name>.yaml`, so the change shows up in `git diff` and comments in the
    file are lost. Saving the same questions again keeps the same version. Every suite whose `question_set` is this
    one asks the new version in its next run. Earlier versions stay available from
    `GET /api/question-sets/{name}/versions`.
    """
    return service.save_question_set(name, body)


@router.get(
    "/question-sets/{name}/versions",
    tags=["question sets"],
    summary="List question set versions",
    response_description="Every version jevtester has seen, newest first.",
)
async def list_question_set_versions(name: QuestionSetName, service: ServiceDep) -> QuestionSetVersions:
    """List a question set's versions, newest first, with how many runs used each.

    jevtester records a version the first time it sees one: when a suite or question set is read or saved, or when a
    run uses one. Pass a version's hash to `GET /api/question-sets/{name}/versions/{version}`, to
    `GET /api/question-sets/{name}/diff`, or as `question_set_version` in `POST /api/runs`.
    """
    return service.question_set_versions(name)


@router.get(
    "/question-sets/{name}/versions/{version}",
    tags=["question sets"],
    summary="Get a question set version",
    response_description="The question set as it was in that version.",
)
async def get_question_set_version(
    name: QuestionSetName,
    version: Annotated[
        str, PathParam(description="The version's SHA-256 hash, or a prefix of it at least 8 characters long.")
    ],
    service: ServiceDep,
) -> QuestionSet:
    """Return one version of a question set.

    A version jevtester hasn't recorded, or a prefix that matches more than one version, returns 404.
    """
    return service.question_set_version(name, version)


@router.get(
    "/question-sets/{name}/diff",
    tags=["question sets"],
    summary="Compare question set versions",
    response_description="How each question changed from one version to the other.",
)
async def diff_question_set(
    name: QuestionSetName,
    from_version: Annotated[
        str, Query(alias="from", description="The older version's hash, or a prefix of 8 or more characters.")
    ],
    to_version: Annotated[
        str, Query(alias="to", description="The newer version's hash, or a prefix of 8 or more characters.")
    ],
    service: ServiceDep,
) -> QuestionSetDiff:
    """Compare two versions of a question set, question by question and option by option."""
    return service.diff_question_set(name, from_version, to_version)


@router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
    summary="Start a run",
    response_description="The new run's id. The run continues in the background.",
)
async def start_run(body: RunCreate, service: ServiceDep) -> RunCreated:
    """Start a run of a suite on the chosen targets, and return its id as soon as it's queued.

    Follow the run with `GET /api/runs/{id}/events`, or poll `GET /api/runs/{id}`. When it finishes, read its scores
    from `GET /api/runs/{id}/metrics` or `GET /api/runs/{id}/report`.

    A run first checks each target's health, and skips every job of a target that's down. Each job's result is cached
    by its target, its request, and its repeat, so a rerun of an unchanged suite sends nothing. Set `no_cache` to send
    every request again. Claude draft cases aren't sent.

    A suite, question set version, or baseline run that doesn't exist returns 404. An unknown target returns 422.
    """
    return await service.start_run(body)


@router.get("/runs", tags=["runs"], summary="List runs", response_description="Every run, newest first.")
async def list_runs(service: ServiceDep) -> RunList:
    """List every run, suite runs and probe runs, newest first."""
    return service.list_runs()


@router.get(
    "/runs/{id}", tags=["runs"], summary="Get a run", response_description="The run's settings, status, and counts."
)
async def get_run(id: RunId, service: ServiceDep) -> RunSummary:
    """Return a run's settings, status, and counts. Poll it to follow a run without the event stream."""
    return service.get_run(id)


@router.get(
    "/runs/{id}/events",
    response_class=EventSourceResponse,
    tags=["runs"],
    summary="Stream run events",
    response_description="The run's events, until it ends.",
)
async def run_events(run: RunDep, service: ServiceDep) -> AsyncIterator[ServerSentEvent]:
    """Stream a run's progress as server-sent events.

    Each event's SSE `event` field is its `type`, its `id` numbers it from 0, and its `data` is a
    [`RunEvent`][jevtester.schemas.RunEvent] as one line of JSON. The first event is always `progress`, with the
    current counts, so a client that reconnects needs no history. A `result` event follows each finished job, and a
    `target_skipped` event each target that's down. A run that has ended sends `progress` and then its final event.

    The stream ends after `finished`, `cancelled`, or `error`. A browser's `EventSource` reconnects when the server
    closes the stream, so close it on the final event. A run that doesn't exist returns 404 before the stream starts.
    """
    async for index, event in _numbered(service.run_events(run.id)):
        yield ServerSentEvent(event=event.type, id=str(index), raw_data=event.model_dump_json())


@router.post("/runs/{id}/cancel", tags=["runs"], summary="Cancel a run", response_description="The run's summary.")
async def cancel_run(id: RunId, service: ServiceDep) -> RunSummary:
    """Cancel a queued or running run, and wait for it to stop.

    Results that arrived before the cancel are kept. Cancelling a run that has ended returns it unchanged, so the call
    is safe to retry.
    """
    return await service.cancel_run(id)


@router.get(
    "/runs/{id}/metrics",
    tags=["runs"],
    summary="Get run metrics",
    response_description="Metrics for each target and question.",
)
async def get_run_metrics(id: RunId, service: ServiceDep) -> RunMetrics:
    """Score a run's answers for each target and question, and its policy's decisions when the suite has a policy.

    The metrics use the cases as the run sent them, so editing the suite later doesn't change them. Only original cases
    count, not probe variants. A metric that doesn't apply to a question's type is `null`.
    """
    return service.run_metrics(id)


@router.get(
    "/runs/{id}/confusion",
    tags=["runs"],
    summary="Get a confusion matrix",
    response_description="Expected options against answered options.",
)
async def get_run_confusion(
    id: RunId, question: QuestionId, target: TargetName, service: ServiceDep
) -> ConfusionMatrix:
    """Count expected options against answered options, for one choice question and one target.

    A question the run didn't ask, a question that isn't a choice, or a target the run didn't run returns 422.
    """
    return service.run_confusion(id, question, target)


@router.get(
    "/runs/{id}/calibration",
    tags=["runs"],
    summary="Get a calibration table",
    response_description="The probability bins and the expected calibration error.",
)
async def get_run_calibration(
    id: RunId,
    question: QuestionId,
    target: TargetName,
    service: ServiceDep,
    bins: Annotated[int, Query(description="The number of equal-width probability bins, from 1 to 100.")] = 10,
) -> Calibration:
    """Build a reliability table for one noul or choice question and one target.

    A reliability table compares the probabilities a target gave with how often it was right. For a noul, the
    prediction is the probability of yes. For a choice, it's the probability of the chosen option, against whether the
    choice was right. A score question, a target the run didn't run, or `bins` outside 1 to 100 returns 422.
    """
    return service.run_calibration(id, question, target, bins)


@router.get(
    "/runs/{id}/changes",
    tags=["runs"],
    summary="Get changed answers",
    response_description="The changed answers, and McNemar's test for each target.",
)
async def get_run_changes(id: RunId, baseline: BaselineId, service: ServiceDep) -> RunChanges:
    """List the answers that changed from a baseline run, with McNemar's test for each target both runs ran.

    The comparison uses the first repeat of each case. McNemar's test is an exact two-sided test on the answers that
    went from wrong to right and from right to wrong. To get both runs' metrics and the regressions too, use
    `GET /api/runs/{id}/compare`.
    """
    return service.run_changes(id, baseline)


@router.get(
    "/runs/{id}/compare",
    tags=["runs"],
    summary="Compare two runs",
    response_description="Both runs' metrics, the changed answers, and the regressions.",
)
async def compare_runs(
    id: RunId,
    baseline: BaselineId,
    service: ServiceDep,
    max_drop: Annotated[
        float | None,
        Query(ge=0, description="The largest allowed drop in a metric. Without it, the config's `defaults.max_drop`."),
    ] = None,
) -> RunComparison:
    """Compare a run with a baseline: both runs' metrics, the changed answers, and any regressions.

    A regression is a target and question whose accuracy, or within-tolerance accuracy for a score, dropped by more
    than `max_drop`. Without `max_drop`, the config's `defaults.max_drop` applies.
    """
    return service.compare_runs(id, baseline, max_drop)


@router.get(
    "/runs/{id}/cases/{case_id}",
    tags=["runs"],
    summary="Get a case in a run",
    response_description="The case, the questions, and every target's full result.",
)
async def get_run_case(
    id: RunId,
    case_id: Annotated[str, PathParam(description="The case's id, like `goblin-bribe`.")],
    service: ServiceDep,
) -> RunCase:
    """Return one case in a run, with every target's full result, whether each answer was right, and any decision.

    Unlike a `result` event, each result here has `request_body` and `raw`. A case the run didn't send returns 404.
    """
    return service.run_case(id, case_id)


@router.get(
    "/runs/{id}/report",
    tags=["runs"],
    summary="Get a run report",
    response_description="The run's summary, its metrics, and the report as Markdown.",
)
async def get_run_report(id: RunId, service: ServiceDep) -> RunReport:
    """Return a run's summary and metrics, and the same report as Markdown.

    When the run has a baseline, the Markdown also lists the answers that changed from it.
    """
    return service.run_report(id)


@router.get(
    "/runs/{id}/probes",
    tags=["probes"],
    summary="Get probe results",
    response_description="How often answers changed, by case, target, and probe.",
)
async def get_run_probes(id: RunId, service: ServiceDep) -> ProbeReport:
    """Report how often each case's answers changed under each probe, for a probe run.

    An instance changed when any answer differs from the original case's answer. A failed request isn't counted. A
    suite run returns 422.
    """
    return service.run_probes(id)


@router.post(
    "/probes",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["probes"],
    summary="Start a probe run",
    response_description="The new run's id. The run continues in the background.",
)
async def start_probe(body: ProbeCreate, service: ServiceDep) -> RunCreated:
    """Start a probe run: each case as written, plus the variants each probe makes of it.

    The run streams events like any run, from `GET /api/runs/{id}/events`, and a `result` event's `variant` names the
    variant, like `option_order:2`. When it ends, `GET /api/runs/{id}/probes` reports it. A probe run sends each
    request once, whatever the config's repeats.
    """
    return await service.start_probe(body)


@router.get(
    "/policies",
    tags=["policies"],
    summary="List policies",
    response_description="Every policy under `suites/policies/`, by name.",
)
async def list_policies(service: ServiceDep) -> PolicyList:
    """List the policies under `suites/policies/`, with each one's actions and the suites that use it."""
    return service.list_policies()


@router.get(
    "/policies/{name}",
    tags=["policies"],
    summary="Get a policy",
    response_description="The policy's YAML text and what it defines.",
)
async def get_policy(name: PolicyName, service: ServiceDep) -> PolicyDetail:
    """Return a policy's YAML text, its actions and thresholds, and the suites that use it."""
    return service.get_policy(name)


@router.put(
    "/policies/{name}",
    tags=["policies"],
    summary="Save a policy",
    response_description="The saved policy.",
)
async def save_policy(name: PolicyName, body: PolicyBody, service: ServiceDep) -> PolicyDetail:
    """Validate a policy's YAML text and save it as sent, comments included. Creates the policy if it's new.

    An invalid policy returns 422 with every error in `details`, and nothing is saved. A YAML syntax error's detail has
    the `line` it's on, from 1.
    """
    return service.save_policy(name, body)


@router.post(
    "/policies/{name}/sweep",
    tags=["policies"],
    summary="Sweep a policy threshold",
    response_description="The share decided, the error rate, and the cost at each value.",
)
async def sweep_policy(name: PolicyName, body: SweepBody, service: ServiceDep) -> SweepResult:
    """Measure a target's decisions in a run as one of the policy's thresholds moves from `start` to `stop`.

    The sweep uses the policy as it is now, against the run's answers, so you can tune a threshold without running the
    suite again. Each value replaces the threshold for the sweep's target, whether the policy sets a shared value or a
    `per_target` one. A threshold the policy doesn't have, a target the run didn't run, or a range of more than 1,000
    points returns 422.
    """
    return service.sweep_policy(name, body)


_EVENTS_PATH = "/api/runs/{id}/events"


def _openapi(app: FastAPI) -> dict[str, Any]:
    # The events route yields ServerSentEvent objects so each event can carry its name, which leaves FastAPI without
    # the payload's type. Add the RunEvent schemas and point the stream's item schema at them.
    if app.openapi_schema is None:
        document = get_openapi(
            title=app.title,
            version=app.version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )
        event_schema = TypeAdapter[RunEvent](RunEvent).json_schema(
            ref_template="#/components/schemas/{model}", mode="serialization"
        )
        schemas = document.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in event_schema.pop("$defs", {}).items():
            schemas.setdefault(name, definition)
        schemas["RunEvent"] = event_schema
        # The OpenAPI 3.2 form for a stream of server-sent events.
        item_schema = {
            "type": "object",
            "required": ["event", "data"],
            "properties": {
                "event": {"type": "string"},
                "id": {"type": "string"},
                "retry": {"type": "integer", "minimum": 0},
                "data": {
                    "type": "string",
                    "contentMediaType": "application/json",
                    "contentSchema": {"$ref": "#/components/schemas/RunEvent"},
                },
            },
        }
        responses = document["paths"][_EVENTS_PATH]["get"]["responses"]
        for code, response in responses.items():
            if code == "200":
                response["content"] = {"text/event-stream": {"itemSchema": item_schema}}
            else:
                # Errors are JSON on every route, this one included.
                response["content"] = {"application/json": response["content"]["text/event-stream"]}
        app.openapi_schema = document
    return app.openapi_schema


DESCRIPTION = """\
The jevtester API gives the web UI and your scripts the same operations as the `jevtester` command line. Start it with
`jevtester serve`. It listens on `http://127.0.0.1:8640`, and every route is under `/api`.

The API has no authentication, because it listens only on this machine. Requests name targets, and the server holds
the credentials, so a client never sees a token.

## Conventions

- Every response field is always present. An unknown value is `null`, never a missing key.
- Times are ISO 8601 in UTC, like `2026-10-24T14:02:00Z`.
- A version is the full SHA-256 hash of the content. A route that takes a version also takes a prefix of 8 or more
  characters.
- Lists keep a meaningful order: targets in the order requested, questions and options in the question set's order,
  and runs newest first.
- Suite, question set, and policy names use lowercase letters, digits, `-`, and `_`.

## Errors

Every 4xx and 5xx response has an `ApiError` body: `{"error": {"code", "message", "field", "details"}}`. `code` is
`invalid_request` (422), `not_found` (404), `conflict` (409), or `internal` (500). `details` lists every validation
error, and `field` is the first one's dotted path. For a question, the path includes the question's type, as in
`questions.intent.choice.criteria`.

A target that fails during a decide request or a run isn't an HTTP error. Its result has `ok: false` and an `error`,
and the other targets' results still arrive.
"""
"""The API's overview, for `info.description` in the OpenAPI document."""

TAGS: list[dict[str, Any]] = [
    {
        "name": "targets",
        "description": (
            "A target is one decision model on one runtime, like `decision-1@foundry`. The config file lists them. "
            "List them with `GET /api/targets`, and run their health checks with `POST /api/targets/check`."
        ),
    },
    {
        "name": "decide",
        "description": (
            "Send one state and its questions to one or more targets, and get their answers in the response. A state "
            "is what the model reads: text, a JSON object, or a JSON array. Use it to try a question before you add "
            "it to a suite."
        ),
    },
    {
        "name": "suites",
        "description": (
            "A suite is a YAML file in `suites/` with cases, the question set they're asked, an optional policy, and "
            "default targets. A case is one state with the answers and action it expects. Read suites, check them, "
            "and add cases here, then run one with `POST /api/runs`."
        ),
    },
    {
        "name": "question sets",
        "description": (
            "A question set is a named set of questions in `suites/question-sets/`. A version is the SHA-256 hash of "
            "its questions in order, so any edit makes a new version. Read and save question sets, list their "
            "versions, and compare two versions here."
        ),
    },
    {
        "name": "runs",
        "description": (
            "A run sends every case in a suite to each target and scores the answers. Start one with `POST /api/runs`, "
            "follow it with `GET /api/runs/{id}/events`, then read `GET /api/runs/{id}/metrics`, "
            "`GET /api/runs/{id}/report`, or `GET /api/runs/{id}/compare`. A job is one case on one target for one "
            "repeat."
        ),
    },
    {
        "name": "probes",
        "description": (
            "A probe changes something about a case that shouldn't change the answers, like the order of a choice's "
            "options, and counts how often they change anyway. Start a probe run with `POST /api/probes`, then read "
            "`GET /api/runs/{id}/probes`."
        ),
    },
    {
        "name": "policies",
        "description": (
            "A policy is a YAML file in `suites/policies/` that turns a result's answers into an action, like "
            "`parley_succeeds` or `escalate`. A suite gives its policy's name in `policy`, and run metrics measure "
            "the policy's decisions. Tune a threshold against a finished run with `POST /api/policies/{name}/sweep`."
        ),
    },
]
"""The tags in the order the reference lists them, with the overview of each."""


def _serve_ui(app: FastAPI, static: Path) -> None:
    # Any path outside /api is the UI's: a built file if one exists, or else index.html, so the UI's own routes
    # like /runs/0002 load on reload. Vite puts the built files under /assets/, so a miss there is a 404.
    root = static.resolve()

    async def ui(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No route /{path}")
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
        if path.startswith("assets/"):
            # A missing built file is a stale or broken build, not one of the UI's routes.
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No file /{path}")
        return FileResponse(root / "index.html")

    app.add_api_route("/{path:path}", ui, methods=["GET"], include_in_schema=False)


def create_app(service: Service | None = None, static: Path | None = STATIC) -> FastAPI:
    """Build the jevtester API app.

    Args:
        service: The service the routes call. `None` loads it from the config on the first request.
        static: The built web UI to serve outside `/api`. Nothing is served there when it has no `index.html`.

    Returns:
        The app, with its routes under `/api`, errors as [`ApiError`][jevtester.schemas.ApiError] bodies, the Vite
        dev server allowed as an origin, and the web UI at `/`.
    """
    app = FastAPI(
        title="jevtester",
        version=__version__,
        summary="Test decision models, the questions written for them, and the decisions built on their answers.",
        description=DESCRIPTION,
        openapi_tags=TAGS,
        # Operation ids are the route functions' names, like `list_targets`, for readable generated clients.
        generate_unique_id_function=lambda route: route.name,
    )
    app.state.service = _ServiceHolder(service)
    app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["*"], allow_headers=["*"])
    app.add_exception_handler(ApiException, _handle_api_exception)
    app.add_exception_handler(ServiceError, _handle_service_error)
    app.add_exception_handler(HTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.include_router(router)
    if static is not None and (static / "index.html").is_file():
        _serve_ui(app, static)
    app.openapi = lambda: _openapi(app)
    return app


def openapi_document() -> str:
    """Render the API's OpenAPI document as it's saved in `docs/openapi.json`.

    Returns:
        The document as indented JSON, with a final newline.
    """
    return json.dumps(create_app(static=None).openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    # `uv run python -m jevtester.api openapi docs/openapi.json` regenerates the saved document.
    if sys.argv[1:2] == ["openapi"] and len(sys.argv) == 3:
        Path(sys.argv[2]).write_text(openapi_document())
    else:
        sys.exit("usage: python -m jevtester.api openapi <path>")
