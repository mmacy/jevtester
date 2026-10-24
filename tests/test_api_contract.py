import json
import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

import api_fixtures
from jevtester.api import create_app, openapi_document, parse_sse, router
from jevtester.schemas import ApiError, RunEvent

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "api"

APP = create_app(api_fixtures.fixture_service(), static=None)
ROUTES = [route for route in router.routes if isinstance(route, APIRoute)]
# Routes the service answers. The targets list has no health check yet, so it matches the unchecked variant.
LIVE_FIXTURES = {"/api/targets": "get_targets.unchecked.json"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(api_fixtures.fixture_service(), static=None))


def saved_fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def fixture_stem(method: str, path: str) -> str:
    return f"{method.lower()}_{path.removeprefix('/api/').replace('/', '_')}"


def sample_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def test_saved_openapi_document_is_current() -> None:
    saved = (ROOT / "docs" / "openapi.json").read_text()
    assert saved == openapi_document(), "Run: uv run python -m jevtester.api openapi docs/openapi.json"


def test_saved_fixtures_are_current(tmp_path: Path) -> None:
    api_fixtures.write(tmp_path)
    built = {path.name: path.read_text() for path in tmp_path.iterdir()}
    saved = {path.name: path.read_text() for path in FIXTURES.iterdir() if path.suffix in {".json", ".sse"}}
    assert sorted(saved) == sorted(built), "Run: uv run python tests/api_fixtures.py"
    for name, text in built.items():
        assert saved[name] == text, f"{name} is stale. Run: uv run python tests/api_fixtures.py"


def test_every_route_has_a_fixture() -> None:
    names = {path.name for path in FIXTURES.iterdir()}
    for route in ROUTES:
        for method in route.methods or set[str]():
            stem = fixture_stem(method, route.path)
            assert f"{stem}.json" in names or f"{stem}.sse" in names, f"No fixture for {method} {route.path}"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.*.json")), ids=lambda path: path.name)
def test_error_fixtures_are_api_errors(path: Path) -> None:
    status = path.name.split(".")[-2]
    if status.isdigit():
        ApiError.model_validate_json(path.read_text())


@pytest.mark.parametrize(
    "route", [r for r in ROUTES if "GET" in (r.methods or set[str]()) and not r.path.endswith("/events")]
)
def test_get_routes_return_their_fixture(client: TestClient, route: APIRoute) -> None:
    params = {"question": "intent", "target": "decision-1@foundry", "baseline": "0141", "from": "a", "to": "b"}
    response = client.get(sample_path(route.path), params=params)
    assert response.status_code == 200
    name = LIVE_FIXTURES.get(route.path, f"{fixture_stem('GET', route.path)}.json")
    assert response.json() == saved_fixture(name)


def test_check_and_decide_return_their_fixtures(client: TestClient) -> None:
    assert client.post("/api/targets/check").json() == saved_fixture("post_targets_check.json")
    goblin = api_fixtures.CASES[0]
    questions = {key: question.model_dump(mode="json") for key, question in api_fixtures.QUESTIONS.items()}
    body = {"state": goblin.state, "questions": questions}
    assert client.post("/api/decide", json=body).json() == saved_fixture("post_decide.json")


def test_decide_rejects_an_unknown_target(client: TestClient) -> None:
    body = {"state": "s", "questions": {"q": {"type": "noul", "instructions": "?"}}, "targets": ["clef@nowhere"]}
    response = client.post("/api/decide", json=body)
    assert response.status_code == 422
    error = ApiError.model_validate(response.json()).error
    assert (error.code, error.field, error.message) == ("invalid_request", "targets.0", "Unknown target: clef@nowhere")


def test_decide_rejects_an_invalid_body_with_every_error(client: TestClient) -> None:
    body = {
        "state": "Six goblins.",
        "questions": {
            "intent": {"type": "choice", "instructions": "?", "criteria": {"only": "One"}},
            "reaction": {"type": "score", "instructions": "?", "criteria": ["One"]},
        },
    }
    response = client.post("/api/decide", json=body)
    assert response.status_code == 422
    error = ApiError.model_validate(response.json()).error
    assert error.code == "invalid_request"
    assert error.field == "questions.intent.choice.criteria"
    assert [detail.field for detail in error.details] == [
        "questions.intent.choice.criteria",
        "questions.reaction.score.criteria",
    ]


def test_decide_accepts_a_minimal_request(client: TestClient) -> None:
    state = api_fixtures.CASES[0].state
    body = {"state": state, "questions": {"bribe": {"type": "noul", "instructions": "A bribe?"}}}
    response = client.post("/api/decide", json=body)
    assert response.status_code == 200
    assert response.json()["results"][0]["target"] == "decision-1@foundry"


def test_unknown_route_is_an_api_error(client: TestClient) -> None:
    response = client.get("/api/nowhere")
    assert response.status_code == 404
    assert ApiError.model_validate(response.json()).error.code == "not_found"


def test_post_routes_answer_with_their_status(client: TestClient) -> None:
    assert client.post("/api/runs", json={"suite": "parley"}).status_code == 202
    assert client.post("/api/probes", json={"suite": "parley", "variants": ["option_order"]}).status_code == 202
    case = {"id": "new", "state": "Two bugbears demand a toll."}
    assert client.post("/api/suites/parley/cases", json=case).status_code == 201


def test_run_events_stream_named_events(client: TestClient) -> None:
    with client.stream("GET", "/api/runs/0142/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())
    adapter = TypeAdapter[RunEvent](RunEvent)
    events = parse_sse(text)
    assert events[0].event == "progress"
    assert events[-1].event == "finished"
    for event in events:
        assert event.raw_data is not None
        payload = adapter.validate_json(event.raw_data)
        assert payload.type == event.event


def test_dev_server_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/api/targets",
        headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    other = client.get("/api/targets", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_openapi_documents_run_events() -> None:
    document = APP.openapi()
    content = document["paths"]["/api/runs/{id}/events"]["get"]["responses"]["200"]["content"]
    data = content["text/event-stream"]["itemSchema"]["properties"]["data"]
    assert data["contentSchema"] == {"$ref": "#/components/schemas/RunEvent"}
    assert "ResultEvent" in document["components"]["schemas"]


def test_routes_are_found() -> None:
    assert len(ROUTES) == len(APP.openapi()["paths"]) + 3  # Three paths have two methods.


def test_ui_is_served_outside_the_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>ui</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    ui = TestClient(create_app(static=tmp_path))
    assert ui.get("/").text == "<html>ui</html>"
    assert ui.get("/runs/0142").text == "<html>ui</html>"
    assert ui.get("/assets/app.js").text == "console.log(1)"
    assert ui.get("/../../etc/passwd").text == "<html>ui</html>"
    assert ui.get("/api/targets").status_code == 200
    missing = ui.get("/api/nowhere")
    assert missing.status_code == 404
    assert ApiError.model_validate(missing.json()).error.code == "not_found"
