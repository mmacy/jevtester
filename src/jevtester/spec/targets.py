"""Targets, their capabilities, and the config file that lists them."""

import tomllib
from pathlib import Path
from typing import Any, Literal, Self, cast

from pydantic import Field, model_validator

from jevtester.model import Model
from jevtester.spec.questions import QuestionType

type ImageFormat = Literal["png", "jpeg", "webp"]


class Capabilities(Model):
    """What a target accepts and returns. `None` means the limit is unknown, so preflight doesn't check it."""

    probabilities: bool = True
    """Whether the target returns a probability for every option. Targets without them are left out of calibration."""
    question_types: list[QuestionType] = Field(default_factory=lambda: list[QuestionType](["noul", "choice", "score"]))
    """The question types the target accepts. Preflight rejects a request with any other type."""
    images: bool = False
    """Whether the target accepts images."""
    max_images: int | None = None
    """The most images one request may have. Preflight rejects a request with more."""
    max_image_bytes: int | None = None
    """The largest image the target accepts, in bytes. Preflight reads each image file at its path as given and rejects
    a request with a larger one."""
    max_total_image_bytes: int | None = None
    """The largest total size of a request's images, in bytes. Preflight rejects a request whose images add up to
    more."""
    image_formats: list[ImageFormat] = Field(default_factory=list[ImageFormat])
    """The image formats the target accepts. Preflight reads each image file's first bytes and rejects a request with an
    image in any other format. Empty means any format."""
    context_window: int | None = None
    """The input limit in tokens. Preflight estimates a request's tokens as its JSON size in bytes divided by 4. Over
    the window, it warns with `state_may_truncate` when the target truncates, and otherwise rejects a request more than
    25% over."""
    truncates_state: bool = False
    """Whether the server cuts the state to fit the context window without an error."""
    max_questions: int | None = None
    """The most questions one request may have. Preflight rejects a request with more."""
    min_options: int | None = None
    """The fewest options or levels a question may have. Preflight rejects a request with a choice or score question
    that has fewer."""
    max_options: int | None = None
    """The most options or levels a question may have. Preflight rejects a request with a choice or score question that
    has more."""
    max_request_bytes: int | None = None
    """The largest request body the target accepts, in bytes of JSON. Preflight rejects a larger request."""
    concurrency: int = Field(default=1, ge=1)
    """How many requests a run may have in flight to the target at once. At least 1."""
    concurrency_group: str | None = None
    """Targets with the same group share one concurrency limit, like several models on one local server."""
    requests_per_minute: int | None = None
    """The most requests a run starts per minute on the target. A run spaces its requests to stay under it."""
    tokens_per_minute: int | None = None
    """The most input tokens a run sends per minute to the target, estimated as preflight does: the request's JSON size
    in bytes divided by 4. A run spaces its requests to stay under it."""
    input_cost_per_mtok_usd: float | None = None
    """The cost of one million input tokens, in US dollars. Output tokens are free on every current target. `None`
    leaves each result's `cost_usd` unknown."""


type ProviderName = Literal["systemone", "workers-ai", "claude"]

type AuthMethod = Literal["azure-cli"]

type Runtime = Literal["foundry", "ollama", "mlx", "workers-ai"]
"""The server a target runs on. Health checks differ by runtime."""


class Target(Model):
    """One model on one runtime, with its settings."""

    name: str
    """The target's id, like `decision-1@foundry`."""
    label: str
    """The name people read, like `Microsoft-Decision-1, Azure Foundry`."""
    provider: ProviderName
    """The provider that sends the target its requests. `systemone` reaches a System One server (Foundry, Ollama, or the
    MLX server) and needs `base_url`. `workers-ai` reaches Cloudflare Workers AI and needs `cloudflare.account_id`.
    `claude` isn't built yet, so its targets never answer."""
    runtime: Runtime | None = None
    """The server the target runs on: `foundry`, `ollama`, `mlx`, or `workers-ai`. It picks the health check. `None` for
    a System One server with no runtime-specific checks."""
    model: str
    """The model name sent in the request body. On Foundry it's the deployment name."""
    base_url: str | None = None
    """The API root. The SystemOne provider appends `/v1/systemone`."""
    auth: AuthMethod | None = None
    """How the provider gets a credential. `azure-cli` reads a token from the `az` sign-in, for Foundry. `None` sends
    none, or uses the provider's own sign-in, like Workers AI's."""
    truncate: bool | None = None
    """The `truncate` field to send, for servers that accept it. `None` leaves it out."""
    capabilities: Capabilities = Field(default_factory=Capabilities)
    """What the target accepts and returns. Preflight checks each request against it before sending."""

    @model_validator(mode="after")
    def _systemone_has_base_url(self) -> Self:
        if self.provider == "systemone" and self.base_url is None:
            raise ValueError("a systemone target needs base_url")
        return self


class Defaults(Model):
    """Values every field without its own setting falls back to."""

    targets: list[str] = Field(default_factory=list[str])
    """The targets a request goes to when it names none, in order. Each must be a key in `targets`."""
    timeout_s: float = Field(default=60.0, gt=0)
    """Seconds to wait for each target's answer. Greater than 0."""
    repeats: int = Field(default=1, ge=1)
    """Times a run sends each case to each target. At least 1."""
    max_drop: float = Field(default=0.05, ge=0)
    """The largest drop in a metric that `jevtester compare` allows before it reports a regression and exits 1."""


class Paths(Model):
    """Where jevtester keeps its files, relative to the config file's directory."""

    suites: str = "suites"
    """Suites, with question sets in `question-sets/` and policies in `policies/` under it."""
    store: str = ".jevtester/runs.sqlite"
    """The SQLite database of runs, results, the cache, and question set versions."""


class CloudflareSettings(Model):
    """Account settings for Workers AI targets."""

    account_id: str | None = None
    """Your Cloudflare account ID, for Workers AI targets. Without it, Workers AI targets are down. Set it in
    `jevtester.local.toml`, which git ignores."""


class Config(Model):
    """The contents of `jevtester.toml`."""

    defaults: Defaults = Field(default_factory=Defaults)
    """Default targets, timeout, repeats, and regression threshold."""
    paths: Paths = Field(default_factory=Paths)
    """Where jevtester keeps suites and its run database."""
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    """Account settings for Workers AI targets."""
    targets: dict[str, Target] = Field(default_factory=dict[str, Target])
    """Targets keyed by name. In TOML, each is a `[targets."<name>"]` table, and the table key is the target's name."""

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


class ConfigError(Exception):
    """A config file can't be read, or isn't UTF-8 TOML. The message names the file and says what's wrong."""


def merge_tables(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge one TOML document over another.

    Args:
        base: The document underneath.
        over: The document on top.

    Returns:
        A new document. Where both have a table under the same key, the tables merge. Otherwise the value in `over`
        wins, so an array in `over` replaces the array in `base`.
    """
    merged = dict(base)
    for key, value in over.items():
        below = merged.get(key)
        if isinstance(below, dict) and isinstance(value, dict):
            merged[key] = merge_tables(cast(dict[str, Any], below), cast(dict[str, Any], value))
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as error:
        raise ConfigError(f"Can't read {path}: {error.strerror or error}") from error
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path} isn't UTF-8 text: byte {error.start} can't be decoded") from error
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path} isn't valid TOML: {error}") from error


def load_config(*paths: Path) -> Config:
    """Read, merge, and validate one or more `jevtester.toml` files.

    Args:
        *paths: The config files, lowest precedence first. Each one is deep-merged over the ones before it with
            [`merge_tables`][jevtester.spec.targets.merge_tables].

    Returns:
        The validated config.

    Raises:
        ConfigError: A file can't be read, or isn't UTF-8 TOML.
        pydantic.ValidationError: The merged files don't match [`Config`][jevtester.spec.targets.Config].
    """
    document: dict[str, Any] = {}
    for path in paths:
        document = merge_tables(document, _read_toml(path))
    return Config.model_validate(document)
