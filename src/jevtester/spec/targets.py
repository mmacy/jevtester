"""Targets, their capabilities, and the config file that lists them."""

import tomllib
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from jevtester.spec.questions import QuestionType


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


type ImageFormat = Literal["png", "jpeg", "webp"]


class Capabilities(_Strict):
    """What a target accepts and returns. `None` means the limit is unknown, so preflight doesn't check it."""

    probabilities: bool = True
    """Whether the target returns a probability for every option. Targets without them are left out of calibration."""
    question_types: list[QuestionType] = Field(default_factory=lambda: list[QuestionType](["noul", "choice", "score"]))
    images: bool = False
    """Whether the target accepts images."""
    max_images: int | None = None
    max_image_bytes: int | None = None
    max_total_image_bytes: int | None = None
    image_formats: list[ImageFormat] = Field(default_factory=list[ImageFormat])
    context_window: int | None = None
    """The input limit in tokens."""
    truncates_state: bool = False
    """Whether the server cuts the state to fit the context window without an error."""
    max_questions: int | None = None
    min_options: int | None = None
    """The fewest options or levels a question may have."""
    max_options: int | None = None
    """The most options or levels a question may have."""
    max_request_bytes: int | None = None
    concurrency: int = Field(default=1, ge=1)
    """How many requests may be in flight at once."""
    concurrency_group: str | None = None
    """Targets with the same group share one concurrency limit, like several models on one local server."""
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None
    input_cost_per_mtok_usd: float | None = None
    """The cost of one million input tokens. Output tokens are free on every current target."""


type ProviderName = Literal["systemone", "workers-ai", "claude"]

type AuthMethod = Literal["azure-cli"]


class Target(_Strict):
    """One model on one runtime, with its settings."""

    name: str
    """The target's id, like `decision-1@foundry`."""
    label: str
    """The name people read, like `Microsoft-Decision-1, Azure Foundry`."""
    provider: ProviderName
    model: str
    """The model name sent in the request body. On Foundry it's the deployment name."""
    base_url: str | None = None
    """The API root. The SystemOne provider appends `/v1/systemone`."""
    auth: AuthMethod | None = None
    """How the provider gets a credential. `None` sends none, or uses the provider's own sign-in."""
    truncate: bool | None = None
    """The `truncate` field to send, for servers that accept it. `None` leaves it out."""
    capabilities: Capabilities = Field(default_factory=Capabilities)


class Defaults(_Strict):
    """Values every field without its own setting falls back to."""

    targets: list[str] = Field(default_factory=list[str])
    timeout_s: float = Field(default=60.0, gt=0)
    repeats: int = Field(default=1, ge=1)


class CloudflareSettings(_Strict):
    """Account settings for Workers AI targets."""

    account_id: str | None = None


class Config(_Strict):
    """The contents of `jevtester.toml`."""

    defaults: Defaults = Field(default_factory=Defaults)
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    targets: dict[str, Target] = Field(default_factory=dict[str, Target])
    """Targets keyed by name."""

    @model_validator(mode="before")
    @classmethod
    def _name_targets(cls, data: Any) -> Any:
        # A target's table key in the TOML file is its name.
        if not isinstance(data, dict):
            return data
        fields = cast(dict[str, Any], data)
        targets = fields.get("targets")
        if isinstance(targets, dict):
            entries = cast(dict[str, Any], targets)
            fields["targets"] = {key: {"name": key, **value} for key, value in entries.items()}
        return fields

    @model_validator(mode="after")
    def _defaults_name_targets(self) -> Self:
        unknown = [name for name in self.defaults.targets if name not in self.targets]
        if unknown:
            raise ValueError(f"defaults.targets names unknown targets: {', '.join(unknown)}")
        return self


def load_config(path: Path) -> Config:
    """Read and validate a `jevtester.toml` file.

    Args:
        path: The config file.

    Returns:
        The validated config.

    Raises:
        OSError: The file can't be read.
        tomllib.TOMLDecodeError: The file isn't valid TOML.
        pydantic.ValidationError: The file doesn't match [`Config`][jevtester.spec.targets.Config].
    """
    return Config.model_validate(tomllib.loads(path.read_text()))
