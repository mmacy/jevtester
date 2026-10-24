import asyncio
import json
from pathlib import Path

import pytest

import api_fixtures
from jevtester import cli
from jevtester.errors import InvalidRequestError
from jevtester.evaluate.probes import OPTION_ORDERS, PAD_KEY, make_variants, probe_report
from jevtester.normalize import ChoiceAnswer, TargetResult
from jevtester.preflight import estimate_tokens
from jevtester.schemas import ProbeCreate, ProbeReport
from jevtester.service import Service
from jevtester.spec import Case, ChoiceQuestion, NoulQuestion, ScoreQuestion
from jevtester.store.runs import StoredResult

CONFIG = api_fixtures.RUN_CONFIG
WORKERS = CONFIG.targets[api_fixtures.WORKERS]
FOUNDRY = CONFIG.targets[api_fixtures.FOUNDRY]
QUESTIONS = api_fixtures.QUESTIONS
GOBLIN = api_fixtures.CASES[0]


def test_option_order_shuffles_every_choice() -> None:
    variants = make_variants(GOBLIN, QUESTIONS, FOUNDRY, ["option_order"])
    assert [v.id for v in variants] == [f"option_order:{i}" for i in range(OPTION_ORDERS)]
    intent0 = QUESTIONS["intent"]
    assert isinstance(intent0, ChoiceQuestion)
    original = list(intent0.criteria)
    for variant in variants:
        intent = variant.request.questions["intent"]
        assert isinstance(intent, ChoiceQuestion)
        assert list(intent.criteria) != original
        assert sorted(intent.criteria) == sorted(original)
        assert variant.request.questions["reaction"] == QUESTIONS["reaction"]
    again = make_variants(GOBLIN, QUESTIONS, FOUNDRY, ["option_order"])
    assert [v.request for v in again] == [v.request for v in variants]


def test_key_order_reverses_a_json_state() -> None:
    [variant] = make_variants(GOBLIN, QUESTIONS, FOUNDRY, ["key_order"])
    state = variant.request.state
    assert isinstance(GOBLIN.state, dict) and isinstance(state, dict)
    assert list(state) == list(reversed(list(GOBLIN.state)))
    text_case = Case(id="t", state="Six goblins.")
    assert make_variants(text_case, QUESTIONS, FOUNDRY, ["key_order"]) == []


def test_bare_levels_replace_score_descriptions() -> None:
    [variant] = make_variants(GOBLIN, QUESTIONS, FOUNDRY, ["bare_levels"])
    reaction = variant.request.questions["reaction"]
    assert isinstance(reaction, ScoreQuestion)
    assert reaction.criteria == ["0", "1", "2", "3", "4"]
    only_noul = {"q": NoulQuestion(instructions="?")}
    assert make_variants(GOBLIN, only_noul, FOUNDRY, ["bare_levels", "option_order"]) == []


def test_pad_state_fills_the_context_window() -> None:
    [variant] = make_variants(GOBLIN, QUESTIONS, WORKERS, ["pad_state"])
    state = variant.request.state
    assert isinstance(state, dict)
    assert PAD_KEY in state
    tokens = estimate_tokens(variant.request.system_one_body(WORKERS.model))
    window = WORKERS.capabilities.context_window
    assert window is not None
    assert 0.85 * window <= tokens <= 0.9 * window
    # Foundry's context window isn't known, so there's nothing to fill.
    assert make_variants(GOBLIN, QUESTIONS, FOUNDRY, ["pad_state"]) == []
    [text] = make_variants(Case(id="t", state="Six goblins."), QUESTIONS, WORKERS, ["pad_state"])
    assert isinstance(text.request.state, str)
    assert text.request.state.startswith("Six goblins.\n\n")


def stored(variant: str | None, choice: str, ok: bool = True) -> StoredResult:
    answer = ChoiceAnswer(choice=choice, probabilities={choice: 1.0}, confidence=1.0)
    result = TargetResult(target="t", ok=ok, answers={"intent": answer} if ok else {})
    return StoredResult(case_id="c", target="t", repeat=0, variant=variant, cached=False, result=result)


def test_probe_report_counts_changed_answers() -> None:
    results = [
        stored(None, "parley"),
        stored("option_order:0", "parley"),
        stored("option_order:1", "fight"),
        stored("option_order:2", "parley", ok=False),
        stored("key_order:0", "parley"),
    ]
    report = probe_report("r", ["option_order", "key_order"], results)
    cells = {cell.variant: cell for cell in report.cells}
    assert (cells["option_order"].instances, cells["option_order"].changed) == (2, 1)
    assert cells["option_order"].change_rate == 0.5
    assert cells["key_order"].change_rate == 0.0
    assert [(s.variant, s.change_rate) for s in report.summary] == [("option_order", 0.5), ("key_order", 0.0)]


def test_probe_report_needs_the_original() -> None:
    report = probe_report("r", ["option_order"], [stored("option_order:0", "parley")])
    assert report.cells == []


# The service


@pytest.fixture
def service(tmp_path: Path) -> Service:
    prepared, _ = api_fixtures.prepared_service(tmp_path)
    return prepared


def test_a_probe_run_has_a_job_for_each_variant(service: Service) -> None:
    summary = service.get_run(api_fixtures.PROBE_RUN)
    assert (summary.kind, summary.variants) == ("probe", ["option_order", "key_order", "bare_levels"])
    # Each case: the original, three option orders, one key order, and one bare-levels variant.
    assert summary.counts.jobs == len(api_fixtures.CASES) * 2 * (1 + OPTION_ORDERS + 1 + 1)
    report = service.run_probes(api_fixtures.PROBE_RUN)
    rates = {(s.target, s.variant): s.change_rate for s in report.summary}
    assert rates[api_fixtures.WORKERS, "bare_levels"] == 1.0
    assert rates[api_fixtures.FOUNDRY, "key_order"] == 0.0


def test_metrics_of_a_probe_run_count_only_the_originals(service: Service) -> None:
    metrics = service.run_metrics(api_fixtures.PROBE_RUN)
    assert {t.results for t in metrics.targets} == {len(api_fixtures.CASES)}


def test_a_suite_run_has_no_probe_report(service: Service) -> None:
    with pytest.raises(InvalidRequestError, match="not a probe run"):
        service.run_probes(api_fixtures.RUN)


def test_a_probe_run_reuses_the_cache(service: Service) -> None:
    async def go() -> str:
        created = await service.start_probe(
            ProbeCreate(suite="parley", targets=[api_fixtures.FOUNDRY], variants=["option_order", "option_order"])
        )
        await service.wait_run(created.id)
        return created.id

    run_id = asyncio.run(go())
    summary = service.get_run(run_id)
    assert summary.variants == ["option_order"]
    assert summary.counts.cached == summary.counts.jobs == len(api_fixtures.CASES) * (1 + OPTION_ORDERS)


def test_cli_probe(service: Service, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(Service, "load", classmethod(lambda cls, path=None: service))
    assert cli.main(["probe", "suites/parley.yaml", "--target", api_fixtures.FOUNDRY]) == 0
    out = capsys.readouterr().out
    assert "decision-1@foundry  option_order  change rate 0.167 over 4 cases" in out
    assert "changed  kobold-retreat  decision-1@foundry  option_order: 2 of 3" in out
    assert cli.main(["probe", "parley", "--variant", "key_order", "--format", "json"]) == 0
    report = ProbeReport.model_validate(json.loads(capsys.readouterr().out))
    assert report.variants == ["key_order"]
