"""Cases, their expected answers, and suites."""

from typing import Literal

from pydantic import Field

from jevtester.model import Model
from jevtester.spec.questions import State


class Expectation(Model):
    """The answer a case expects to one question."""

    answer: bool | str | int | None = None
    """`True` or `False` for a noul, an option name for a choice, or a level index for a score."""
    acceptable: list[str | int] | None = None
    """Other answers that count as correct."""
    tolerance: int = Field(default=0, ge=0)
    """Score levels of slack."""


type Provenance = Literal["human", "claude-draft"]
"""Who wrote a case. Evaluation ignores `claude-draft` cases until a person approves them."""


class Case(Model):
    """One state, with the answers and action it expects."""

    id: str = Field(min_length=1)
    state: State
    images: list[str] = Field(default_factory=list[str])
    """Paths of image files sent with the state."""
    expected: dict[str, Expectation] = Field(default_factory=dict[str, Expectation])
    """Expected answers keyed by question id."""
    expected_action: str | None = None
    """The action a policy should choose, for policy tests."""
    tags: list[str] = Field(default_factory=list[str])
    provenance: Provenance = "human"


class Suite(Model):
    """Cases, the question set they're asked, an optional policy, and default targets."""

    name: str
    question_set: str
    """The name of the question set."""
    cases: list[Case] = Field(default_factory=list[Case])
    policy: str | None = None
    """The name of the policy that turns answers into actions."""
    targets: list[str] = Field(default_factory=list[str])
    """Target names to run when a run names none. Empty means the config's default targets."""
