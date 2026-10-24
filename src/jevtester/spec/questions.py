"""Questions, question sets, and the request every decision model accepts."""

import hashlib
import json
from typing import Annotated, Any, Literal, cast

from pydantic import Field, JsonValue, computed_field, model_validator

from jevtester.model import Model

type State = str | dict[str, JsonValue] | list[JsonValue]
"""What a decision model reads: text, a JSON object, or a JSON array."""


class NoulCriteria(Model):
    """Optional descriptions of the yes and no outcomes of a noul question."""

    true: str | None = None
    """What counts as yes."""
    false: str | None = None
    """What counts as no."""


class NoulQuestion(Model):
    """A yes/no question. Its answer is the probability of yes."""

    type: Literal["noul"] = "noul"
    instructions: str
    """The question. The model sees this text and not the question's id."""
    criteria: NoulCriteria | None = None
    """Descriptions of yes and no. Not every server accepts them."""


class ChoiceQuestion(Model):
    """A question that picks one option from a map of option names to descriptions."""

    type: Literal["choice"] = "choice"
    instructions: str
    """The question. The model sees this text and not the question's id."""
    criteria: dict[str, str] = Field(min_length=2)
    """Option names mapped to descriptions, in the order sent to the model."""


class ScoreQuestion(Model):
    """A question that places the state on an ordered list of levels, lowest first."""

    type: Literal["score"] = "score"
    instructions: str
    """The question. The model sees this text and not the question's id."""
    criteria: list[str] = Field(min_length=2)
    """One description per level, lowest first. Level `i` is `criteria[i]`."""


type Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]
"""Any question, told apart by its `type`."""

type QuestionType = Literal["noul", "choice", "score"]
"""The question types jevtester supports."""


def _questions_body(questions: dict[str, Question]) -> dict[str, Any]:
    return {key: question.model_dump(mode="json", exclude_none=True) for key, question in questions.items()}


class QuestionSet(Model):
    """A named set of questions. Its content hash identifies a version."""

    name: str
    questions: dict[str, Question] = Field(min_length=1)
    """Questions keyed by the id each answer comes back under."""

    @model_validator(mode="before")
    @classmethod
    def _drop_version(cls, data: Any) -> Any:
        # A saved question set may carry the `version` it was written with. The hash is always recomputed.
        if not isinstance(data, dict):
            return data
        fields = dict(cast(dict[str, Any], data))
        fields.pop("version", None)
        return fields

    @computed_field
    @property
    def version(self) -> str:
        """The SHA-256 hash of the questions as sent, in order. The name isn't part of it."""
        encoded = json.dumps(_questions_body(self.questions), separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode()).hexdigest()


class DecisionRequest(Model):
    """One request to a decision model, before a target adds its model name and settings."""

    state: State
    questions: dict[str, Question] = Field(min_length=1)
    """Questions keyed by the id each answer comes back under."""
    images: list[str] = Field(default_factory=list[str])
    """Paths of image files sent with the state."""

    def system_one_body(self, model: str, *, extra: dict[str, JsonValue] | None = None) -> dict[str, Any]:
        """Build the System One request body for one target.

        Args:
            model: The target's model name, as the server expects it in the body.
            extra: Fields a target adds to the body, like `{"truncate": false}` for the MLX server.

        Returns:
            The JSON body, with questions and options in the order given. Images aren't included, since each runtime
            sends them differently.
        """
        body: dict[str, Any] = {"model": model, "state": self.state, "questions": _questions_body(self.questions)}
        if extra:
            body.update(extra)
        return body
