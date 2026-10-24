"""Probes: variants of each case that shouldn't change the answers, and how often they do.

A decision model's answers can depend on wording and order that shouldn't matter. Each probe changes one such thing
and keeps the meaning, so a changed answer points at a fragile question or model.
"""

import json
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import JsonValue

from jevtester.evaluate.metrics import originals
from jevtester.evaluate.scoring import answer_value
from jevtester.preflight import estimate_tokens
from jevtester.schemas import ProbeCell, ProbeReport, ProbeSummary, ProbeVariant
from jevtester.spec import Case, ChoiceQuestion, DecisionRequest, Question, ScoreQuestion, State, Target
from jevtester.store.runs import StoredResult

OPTION_ORDERS = 3
"""Shuffles of choice options made for each case."""
PAD_SHARE = 0.9
"""How far `pad_state` fills a target's context window."""
PADDING = "Nothing else in the scene changes. "
"""Neutral text that `pad_state` repeats. It adds no fact a question could turn on."""
PAD_KEY = "notes"


@dataclass(frozen=True)
class Variant:
    """One variant request made from a case."""

    probe: ProbeVariant
    index: int
    request: DecisionRequest

    @property
    def id(self) -> str:
        """The variant's id, like `option_order:2`."""
        return f"{self.probe}:{self.index}"


def _shuffled(question: ChoiceQuestion, seed: str) -> ChoiceQuestion:
    options = list(question.criteria.items())
    order = options[:]
    random.Random(seed).shuffle(order)
    if order == options:
        # A shuffle that changed nothing tests nothing, so rotate instead.
        order = options[1:] + options[:1]
    return question.model_copy(update={"criteria": dict(order)})


def _reversed_keys(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        items = cast(dict[str, JsonValue], value).items()
        return {key: _reversed_keys(item) for key, item in reversed(list(items))}
    if isinstance(value, list):
        return [_reversed_keys(item) for item in cast(list[JsonValue], value)]
    return value


def _padded(state: State, target: Target, request: DecisionRequest) -> State | None:
    window = target.capabilities.context_window
    if window is None:
        return None
    room = int(window * PAD_SHARE) - estimate_tokens(request.system_one_body(target.model))
    if room <= 0:
        return None
    # estimate_tokens counts 4 bytes a token, so the padding has 4 bytes for each token of room, less the bytes the
    # padding's key or separator adds.
    overhead = len(json.dumps({PAD_KEY: ""})) if isinstance(state, dict) else len(json.dumps("\n\n"))
    size = room * 4 - overhead
    padding = (PADDING * (size // len(PADDING) + 1))[:size].strip()
    if isinstance(state, str):
        return f"{state}\n\n{padding}"
    if isinstance(state, dict):
        return {**state, PAD_KEY: padding}
    return [*state, padding]


def make_variants(
    case: Case, questions: Mapping[str, Question], target: Target, probes: Sequence[ProbeVariant]
) -> list[Variant]:
    """Make each probe's variants of one case for one target.

    Args:
        case: The case.
        questions: The questions the run asks.
        target: The target, whose context window `pad_state` fills.
        probes: The probes to make.

    Returns:
        The variants. A probe makes none when it doesn't apply: `option_order` needs a choice question, `key_order`
        a JSON object in the state, `bare_levels` a score question, and `pad_state` a known context window.
    """
    base = DecisionRequest(state=case.state, questions=dict(questions), images=case.images)
    variants: list[Variant] = []
    for probe in probes:
        match probe:
            case "option_order":
                if not any(isinstance(q, ChoiceQuestion) for q in questions.values()):
                    continue
                for index in range(OPTION_ORDERS):
                    shuffled = {
                        key: _shuffled(q, f"{case.id}:{key}:{index}") if isinstance(q, ChoiceQuestion) else q
                        for key, q in questions.items()
                    }
                    variants.append(Variant(probe, index, base.model_copy(update={"questions": shuffled})))
            case "key_order":
                reordered = _reversed_keys(case.state)
                if json.dumps(reordered) == json.dumps(case.state):
                    continue
                variants.append(Variant(probe, 0, base.model_copy(update={"state": reordered})))
            case "bare_levels":
                if not any(isinstance(q, ScoreQuestion) for q in questions.values()):
                    continue
                bare: dict[str, Question] = {
                    key: q.model_copy(update={"criteria": [str(level) for level in range(len(q.criteria))]})
                    if isinstance(q, ScoreQuestion)
                    else q
                    for key, q in questions.items()
                }
                variants.append(Variant(probe, 0, base.model_copy(update={"questions": bare})))
            case "pad_state":
                padded = _padded(case.state, target, base)
                if padded is not None:
                    variants.append(Variant(probe, 0, base.model_copy(update={"state": padded})))
    return variants


def _values(result: StoredResult) -> dict[str, Any]:
    return {key: answer_value(answer) for key, answer in result.result.answers.items()}


def probe_report(run_id: str, probes: Sequence[ProbeVariant], results: Sequence[StoredResult]) -> ProbeReport:
    """Count how often each case's answers changed under each probe, for each target.

    An instance changed when any answer differs from the original request's answer on the first repeat. A failed
    request on either side isn't counted.

    Args:
        run_id: The probe run's id.
        probes: The probes the run made.
        results: The run's results.

    Returns:
        A cell for each case, target, and probe with any instances, and a summary for each target and probe.
    """
    first = {(r.target, r.case_id): r for r in reversed(originals(results)) if r.repeat == 0 and r.result.ok}
    tallies: dict[tuple[str, str, ProbeVariant], list[int]] = {}
    for stored in results:
        if stored.variant is None or not stored.result.ok:
            continue
        probe = cast(ProbeVariant, stored.variant.split(":")[0])
        original = first.get((stored.target, stored.case_id))
        if original is None:
            continue
        tally = tallies.setdefault((stored.case_id, stored.target, probe), [0, 0])
        tally[0] += 1
        tally[1] += _values(stored) != _values(original)
    cells = [
        ProbeCell(
            case_id=case_id,
            target=target,
            variant=probe,
            instances=instances,
            changed=changed,
            change_rate=changed / instances if instances else None,
        )
        for (case_id, target, probe), (instances, changed) in tallies.items()
    ]
    summary: list[ProbeSummary] = []
    for target in dict.fromkeys(cell.target for cell in cells):
        for probe in probes:
            group = [cell for cell in cells if cell.target == target and cell.variant == probe]
            instances = sum(cell.instances for cell in group)
            summary.append(
                ProbeSummary(
                    target=target,
                    variant=probe,
                    cases=len(group),
                    change_rate=sum(cell.changed for cell in group) / instances if instances else None,
                )
            )
    return ProbeReport(run_id=run_id, variants=list(probes), cells=cells, summary=summary)
