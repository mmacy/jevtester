"""The jevtester HTTP API.

The targets and decide routes call `service.py`. Every other route answers from a fixture in `tests/fixtures/api/`
until the build step that makes its data real replaces it with a service call. The routes, their models, and
`docs/openapi.json` are the contract either way.
"""

import json
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, TypeAdapter
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

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "api"
STATIC = Path(__file__).resolve().parent / "static"
"""The built web UI. The frontend build writes it, and git ignores it."""

_STATUS_CODES: dict[int, ApiErrorCode] = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "invalid_request",
}

_ERRORS: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ApiError, "description": "Not found"},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ApiError, "description": "Invalid request"},
    status.HTTP_500_INTERNAL_SERVER_ERROR: {"model": ApiError, "description": "Server error"},
}
_CONFLICT: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"model": ApiError, "description": "Conflict, or a target that isn't ready"}
}


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
    details = [ErrorDetail(field=exc.field, message=str(exc))] if exc.code == "invalid_request" else []
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


def _fixture[M: BaseModel](name: str, model: type[M]) -> M:
    path = FIXTURES / f"{name}.json"
    if not path.is_file():
        raise ApiException(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal", f"No fixture {path.name}.")
    return model.model_validate_json(path.read_text())


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


def _run(id: str, service: ServiceDep) -> RunSummary:
    # A dependency, so an unknown run is a 404 before the event stream starts.
    return service.get_run(id)


type RunDep = Annotated[RunSummary, Depends(_run)]


async def _numbered[T](items: AsyncIterator[T]) -> AsyncIterator[tuple[int, T]]:
    index = 0
    async for item in items:
        yield index, item
        index += 1


router = APIRouter(prefix="/api", responses=_ERRORS)


@router.get("/targets", tags=["targets"])
async def list_targets(service: ServiceDep) -> TargetList:
    """List targets, their capabilities, and their last health check."""
    return service.list_targets()


@router.post("/targets/check", tags=["targets"])
async def check_targets(service: ServiceDep) -> TargetList:
    """Run every target's health check and return the targets with the results."""
    return await service.check_targets()


@router.post("/decide", tags=["decide"])
async def decide(body: DecideBody, service: ServiceDep) -> DecideResponse:
    """Send one request to each chosen target and return one result per target.

    A target that can't take the request, because it isn't ready or a preflight check fails, still has a result,
    with `ok: false` and an error.
    """
    return await service.decide(body)


@router.get("/suites", tags=["suites"])
async def list_suites(service: ServiceDep) -> SuiteList:
    """List the suites under `suites/`."""
    return service.list_suites()


@router.get("/suites/{name}", tags=["suites"])
async def get_suite(name: str, service: ServiceDep) -> SuiteDetail:
    """Return a suite with its cases and its question set's current version."""
    return service.get_suite(name)


@router.get("/suites/{name}/check", tags=["suites"])
async def check_suite(name: str) -> SuiteCheck:
    """Validate a suite and run the question-wording checks on its question set."""
    return _fixture("get_suites_{name}_check", SuiteCheck)


@router.post("/suites/{name}/cases", status_code=status.HTTP_201_CREATED, tags=["suites"], responses=_CONFLICT)
async def add_case(name: str, case: Case, service: ServiceDep) -> CaseCreated:
    """Add a case to a suite's YAML file. A case id the suite already has is a conflict."""
    return service.add_case(name, case)


@router.get("/question-sets", tags=["question sets"])
async def list_question_sets(service: ServiceDep) -> QuestionSetList:
    """List the question sets under `suites/`."""
    return service.list_question_sets()


@router.get("/question-sets/{name}", tags=["question sets"])
async def get_question_set(name: str, service: ServiceDep) -> QuestionSetDetail:
    """Return a question set's current version, the suites that use it, and its wording checks."""
    return service.get_question_set(name)


@router.put("/question-sets/{name}", tags=["question sets"])
async def save_question_set(name: str, body: QuestionSetBody, service: ServiceDep) -> QuestionSetDetail:
    """Save new questions to a question set's YAML file, which makes a new version. Creates the set if it's new."""
    return service.save_question_set(name, body)


@router.get("/question-sets/{name}/versions", tags=["question sets"])
async def list_question_set_versions(name: str, service: ServiceDep) -> QuestionSetVersions:
    """List a question set's versions by hash, newest first."""
    return service.question_set_versions(name)


@router.get("/question-sets/{name}/versions/{version}", tags=["question sets"])
async def get_question_set_version(name: str, version: str, service: ServiceDep) -> QuestionSet:
    """Return one version of a question set."""
    return service.question_set_version(name, version)


@router.get("/question-sets/{name}/diff", tags=["question sets"])
async def diff_question_set(
    name: str,
    from_version: Annotated[str, Query(alias="from")],
    to_version: Annotated[str, Query(alias="to")],
    service: ServiceDep,
) -> QuestionSetDiff:
    """Compare two versions of a question set."""
    return service.diff_question_set(name, from_version, to_version)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED, tags=["runs"])
async def start_run(body: RunCreate, service: ServiceDep) -> RunCreated:
    """Start a run of a suite on the chosen targets. Follow it with `GET /api/runs/{id}/events`."""
    return await service.start_run(body)


@router.get("/runs", tags=["runs"])
async def list_runs(service: ServiceDep) -> RunList:
    """List runs, newest first."""
    return service.list_runs()


@router.get("/runs/{id}", tags=["runs"])
async def get_run(id: str, service: ServiceDep) -> RunSummary:
    """Return a run's settings, status, and counts."""
    return service.get_run(id)


@router.get("/runs/{id}/events", response_class=EventSourceResponse, tags=["runs"])
async def run_events(run: RunDep, service: ServiceDep) -> AsyncIterator[ServerSentEvent]:
    """Stream a run's progress as server-sent events.

    Each event's SSE `event` field is its `type`, and its `data` is a [`RunEvent`][jevtester.schemas.RunEvent] as
    JSON. The first event is always `progress`, with the current counts, so a client that reconnects needs no
    history. A run that has ended sends `progress` and then its final event. The stream ends after `finished`,
    `cancelled`, or `error`.
    """
    async for index, event in _numbered(service.run_events(run.id)):
        yield ServerSentEvent(event=event.type, id=str(index), raw_data=event.model_dump_json())


@router.post("/runs/{id}/cancel", tags=["runs"])
async def cancel_run(id: str, service: ServiceDep) -> RunSummary:
    """Cancel a queued or running run. Cancelling a run that has ended returns it unchanged."""
    return await service.cancel_run(id)


@router.get("/runs/{id}/metrics", tags=["runs"])
async def get_run_metrics(id: str) -> RunMetrics:
    """Return metrics for each target and question."""
    return _fixture("get_runs_{id}_metrics", RunMetrics)


@router.get("/runs/{id}/confusion", tags=["runs"])
async def get_run_confusion(id: str, question: str, target: str) -> ConfusionMatrix:
    """Return the confusion matrix for one choice question and one target."""
    return _fixture("get_runs_{id}_confusion", ConfusionMatrix)


@router.get("/runs/{id}/calibration", tags=["runs"])
async def get_run_calibration(id: str, question: str, target: str, bins: int = 10) -> Calibration:
    """Return a reliability table for one noul or choice question and one target."""
    return _fixture("get_runs_{id}_calibration", Calibration)


@router.get("/runs/{id}/changes", tags=["runs"])
async def get_run_changes(id: str, baseline: str) -> RunChanges:
    """Return the answers that changed from a baseline run, with McNemar's test for each target."""
    return _fixture("get_runs_{id}_changes", RunChanges)


@router.get("/runs/{id}/cases/{case_id}", tags=["runs"])
async def get_run_case(id: str, case_id: str) -> RunCase:
    """Return one case in a run, with every target's full result."""
    return _fixture("get_runs_{id}_cases_{case_id}", RunCase)


@router.get("/runs/{id}/report", tags=["runs"])
async def get_run_report(id: str) -> RunReport:
    """Return a run's summary and metrics, and the same report as Markdown."""
    return _fixture("get_runs_{id}_report", RunReport)


@router.get("/runs/{id}/probes", tags=["probes"])
async def get_run_probes(id: str) -> ProbeReport:
    """Return how often each case's answers changed under each probe variant."""
    return _fixture("get_runs_{id}_probes", ProbeReport)


@router.post("/probes", status_code=status.HTTP_202_ACCEPTED, tags=["probes"])
async def start_probe(body: ProbeCreate) -> RunCreated:
    """Start a probe run. It streams events like any run, and `GET /api/runs/{id}/probes` returns its results."""
    return _fixture("post_probes", RunCreated)


@router.get("/policies", tags=["policies"])
async def list_policies() -> PolicyList:
    """List the policies under `suites/`."""
    return _fixture("get_policies", PolicyList)


@router.get("/policies/{name}", tags=["policies"])
async def get_policy(name: str) -> PolicyDetail:
    """Return a policy's YAML text and what it defines."""
    return _fixture("get_policies_{name}", PolicyDetail)


@router.put("/policies/{name}", tags=["policies"])
async def save_policy(name: str, body: PolicyBody) -> PolicyDetail:
    """Validate and save a policy's YAML text. An invalid policy returns 422 with every error in `details`."""
    return _fixture("put_policies_{name}", PolicyDetail)


@router.post("/policies/{name}/sweep", tags=["policies"])
async def sweep_policy(name: str, body: SweepBody) -> SweepResult:
    """Sweep one threshold over a finished run's answers and return the trade-off points."""
    return _fixture("post_policies_{name}_sweep", SweepResult)


_EVENTS_PATH = "/api/runs/{id}/events"


def _openapi(app: FastAPI) -> dict[str, Any]:
    # The events route yields ServerSentEvent objects so each event can carry its name, which leaves FastAPI without
    # the payload's type. Add the RunEvent schemas and point the stream's item schema at them.
    if app.openapi_schema is None:
        document = get_openapi(title=app.title, version=app.version, summary=app.summary, routes=app.routes)
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


def _serve_ui(app: FastAPI, static: Path) -> None:
    # Any path outside /api is the UI's: a built file if one exists, or else index.html, so the UI's own routes
    # like /runs/0142 load on reload.
    root = static.resolve()

    async def ui(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No route /{path}")
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
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
