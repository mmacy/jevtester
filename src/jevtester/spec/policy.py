"""Decision policies: how answers become an action, like `parley_succeeds` or `escalate`.

A policy is YAML under `suites/policies/`. Its conditions are data, not expressions, so a policy can't run code.
"""

import hashlib
import json
from typing import Any, Self, cast

from pydantic import Field, computed_field, model_validator

from jevtester.model import Model

type Bound = float | str
"""A number, or the name of one of the policy's thresholds."""


class Range(Model):
    """A numeric condition. Both ends are inclusive, and either can be left out."""

    at_least: Bound | None = None
    at_most: Bound | None = None


type Condition = str | list[str] | bool | Range
"""What a rule needs from a question or composite.

An option name, or a list of them, for a choice. `true` or `false` for a noul. A `Range` for a noul's probability of
yes, a score's `score`, or a composite.
"""


class Band(Model):
    """Confidence bands for one question.

    At `act` or above, the policy acts. At `confirm` or above, it acts and marks the decision for confirmation. Below
    `confirm`, it escalates.
    """

    act: Bound
    confirm: Bound


class Rule(Model):
    """An action and the conditions it needs. Every condition must hold."""

    action: str = Field(min_length=1)
    when: dict[str, Condition] = Field(default_factory=dict[str, Condition])
    """Conditions keyed by question id or composite name. An empty `when` always matches."""


class Policy(Model):
    """A decision policy."""

    name: str
    thresholds: dict[str, float] = Field(default_factory=dict[str, float])
    """Named numbers that bands and ranges refer to, so a sweep can move them."""
    per_target: dict[str, dict[str, float]] = Field(default_factory=dict[str, dict[str, float]])
    """Threshold values for one target, keyed by target name. Probabilities differ between models."""
    bands: dict[str, Band] = Field(default_factory=dict[str, Band])
    """Confidence bands keyed by question id."""
    composites: dict[str, dict[str, float]] = Field(default_factory=dict[str, dict[str, float]])
    """Weighted sums of answers, keyed by name. Each maps question ids to weights.

    A noul contributes its probability of yes, a score its `score` divided by its top level, and a choice the
    probability of its chosen option.
    """
    rules: list[Rule] = Field(min_length=1)
    """Checked in order. The first rule whose conditions all hold gives the action."""
    default: str = "escalate"
    """The action when no rule matches."""
    escalate: str = "escalate"
    """The action when a banded question's confidence is below its `confirm` value."""
    costs: dict[str, dict[str, float]] | None = None
    """The cost of choosing an action when the case expected another, as `costs[expected][chosen]`. A wrong choice
    that isn't listed costs 1. `None` leaves cost out of the metrics."""

    @model_validator(mode="before")
    @classmethod
    def _drop_version(cls, data: Any) -> Any:
        # A stored policy may carry the `version` it was saved with. The hash is always recomputed.
        if not isinstance(data, dict):
            return data
        fields = dict(cast(dict[str, Any], data))
        fields.pop("version", None)
        return fields

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        known = set(self.thresholds)
        for target, values in self.per_target.items():
            unknown = sorted(set(values) - known)
            if unknown:
                raise ValueError(f"per_target.{target} sets unknown thresholds: {', '.join(unknown)}")
        bounds: list[tuple[str, Bound | None]] = []
        for key, band in self.bands.items():
            bounds += [(f"bands.{key}.act", band.act), (f"bands.{key}.confirm", band.confirm)]
        for index, rule in enumerate(self.rules):
            for key, condition in rule.when.items():
                if isinstance(condition, Range):
                    prefix = f"rules.{index}.when.{key}"
                    bounds += [(f"{prefix}.at_least", condition.at_least), (f"{prefix}.at_most", condition.at_most)]
        for where, bound in bounds:
            if isinstance(bound, str) and bound not in known:
                raise ValueError(f"{where} names the unknown threshold {bound}")
        read = set(self.bands) | {key for weights in self.composites.values() for key in weights}
        clashes = sorted(set(self.composites) & read)
        if clashes:
            raise ValueError(f"A composite can't share a name with a question: {', '.join(clashes)}")
        return self

    @computed_field
    @property
    def version(self) -> str:
        """The SHA-256 hash of the policy as parsed. The name, comments, and layout aren't part of it."""
        data = self.model_dump(mode="json", exclude={"name", "version"})
        return hashlib.sha256(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    @property
    def actions(self) -> list[str]:
        """Every action the policy can choose, in the order it names them."""
        names = [rule.action for rule in self.rules] + [self.default, self.escalate]
        return list(dict.fromkeys(names))

    def threshold(self, name: str, target: str | None) -> float:
        """Look up a threshold for a target.

        Args:
            name: The threshold's name.
            target: The target's name. `None` uses the shared value.

        Returns:
            The target's value when the policy sets one, or else the shared value.
        """
        if target is not None and name in self.per_target.get(target, {}):
            return self.per_target[target][name]
        return self.thresholds[name]

    def questions(self) -> set[str]:
        """The question ids and composite names the policy reads."""
        names = set(self.bands) | {key for weights in self.composites.values() for key in weights}
        names |= {key for rule in self.rules for key in rule.when}
        return names - set(self.composites)
