"""The operations the CLI and the API both call.

Each operation takes and returns the models in [`jevtester.schemas`][jevtester.schemas], so the CLI's JSON output
and the API's responses are the same.
"""

import asyncio
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from jevtester.credentials import AzureCliToken
from jevtester.normalize import ResultError, ResultWarning, TargetResult
from jevtester.preflight import preflight, target_warnings
from jevtester.providers import DecisionProvider, Health, RawResult, target_result
from jevtester.providers.systemone import SystemOneProvider
from jevtester.schemas import DecideBody, DecideResponse, TargetInfo, TargetList, TargetStatus
from jevtester.spec import Config, DecisionRequest, QuestionSet, Target, load_config

CONFIG_ENV = "JEVTESTER_CONFIG"
"""An environment variable naming the config file. Without it, jevtester reads `jevtester.toml` here."""
HEALTH_CHECK_TIMEOUT_S = 15.0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
TIMEOUT_GRACE_S = 5.0
"""Extra seconds before jevtester gives up on a provider that doesn't honor its own timeout."""


class UnknownTargetError(ValueError):
    """A request names a target the config doesn't have, or names one twice."""

    def __init__(self, message: str, index: int) -> None:
        """Describe the target name that can't be used.

        Args:
            message: What's wrong with the name.
            index: Its position in the list of target names.
        """
        super().__init__(message)
        self.field = f"targets.{index}"


def config_path() -> Path:
    """Find the config file.

    Returns:
        The path in `JEVTESTER_CONFIG`, or `jevtester.toml` in the working directory.
    """
    return Path(os.environ.get(CONFIG_ENV) or "jevtester.toml")


def build_providers(config: Config) -> dict[str, DecisionProvider]:
    """Build a provider for each target whose provider exists.

    Args:
        config: The config.

    Returns:
        Providers keyed by target name. Targets whose provider isn't built yet are left out.
    """
    azure = AzureCliToken()
    providers: dict[str, DecisionProvider] = {}
    for target in config.targets.values():
        if target.provider == "systemone":
            credential = azure if target.auth == "azure-cli" else None
            providers[target.name] = SystemOneProvider(target, credential)
    return providers


def is_local(target: Target) -> bool:
    """Whether a target runs on this machine.

    Args:
        target: The target.

    Returns:
        `True` when its base URL's host is this machine.
    """
    return target.base_url is not None and urlparse(target.base_url).hostname in LOCAL_HOSTS


class Service:
    """jevtester's operations over one config and its providers."""

    def __init__(
        self,
        config: Config,
        providers: Mapping[str, DecisionProvider],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Serve one config.

        Args:
            config: The targets and defaults.
            providers: A provider for each target that has one, keyed by target name.
            clock: The current time, for tests.
        """
        self.config = config
        self._providers = dict(providers)
        self._clock = clock
        self._health: dict[str, tuple[Health, datetime]] = {}
        self._checked_at: datetime | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> Service:
        """Load the config and build its providers.

        Args:
            path: The config file. `None` uses [`config_path`][jevtester.service.config_path].

        Returns:
            The service.
        """
        config = load_config(path or config_path())
        return cls(config, build_providers(config))

    # Targets

    def _missing_reason(self, target: Target) -> str:
        return f"The {target.provider} provider isn't built yet"

    def target_info(self, target: Target) -> TargetInfo:
        """Describe a target with its last health check.

        Args:
            target: The target.

        Returns:
            The target's status, reason, credential source, warnings, and capabilities.
        """
        warnings = target_warnings(target)
        checked = self._health.get(target.name)
        status: TargetStatus
        health = Health()
        checked_at: datetime | None = None
        if checked is None:
            status = "unchecked"
        else:
            health, checked_at = checked
            status = "down" if health.reason else "warning" if warnings else "ready"
        return TargetInfo(
            name=target.name,
            label=target.label,
            provider=target.provider,
            model=target.model,
            base_url=target.base_url,
            local=is_local(target),
            status=status,
            reason=health.reason,
            detail=health.detail,
            credential=health.credential,
            warnings=warnings,
            checked_at=checked_at,
            capabilities=target.capabilities,
        )

    def list_targets(self) -> TargetList:
        """List every target with its last health check.

        Returns:
            The targets in config order.
        """
        return TargetList(
            targets=[self.target_info(target) for target in self.config.targets.values()],
            default_targets=list(self.config.defaults.targets),
            checked_at=self._checked_at,
        )

    async def _check(self, target: Target) -> Health:
        provider = self._providers.get(target.name)
        if provider is None:
            return Health(reason=self._missing_reason(target))
        try:
            return await asyncio.wait_for(provider.health_check(), HEALTH_CHECK_TIMEOUT_S)
        except TimeoutError:
            return Health(reason="The health check timed out", detail=f"No answer in {HEALTH_CHECK_TIMEOUT_S:g} s")

    async def check_targets(self) -> TargetList:
        """Run every target's health check at once.

        Returns:
            The targets with the new results.
        """
        targets = list(self.config.targets.values())
        results = await asyncio.gather(*(self._check(target) for target in targets))
        now = self._clock()
        for target, health in zip(targets, results, strict=True):
            self._health[target.name] = (health, now)
        self._checked_at = now
        return self.list_targets()

    def resolve_targets(self, names: list[str]) -> list[Target]:
        """Look up targets by name.

        Args:
            names: Target names, or `["all"]` for every target. Empty means the config's default targets.

        Returns:
            The targets, in the order named.

        Raises:
            UnknownTargetError: A name isn't in the config, or is given twice.
        """
        if names == ["all"]:
            return list(self.config.targets.values())
        chosen = names or self.config.defaults.targets
        targets: list[Target] = []
        for index, name in enumerate(chosen):
            target = self.config.targets.get(name)
            if target is None:
                raise UnknownTargetError(f"Unknown target: {name}", index)
            if target in targets:
                raise UnknownTargetError(f"{name} is named twice", index)
            targets.append(target)
        return targets

    # Decide

    async def _decide_one(self, target: Target, request: DecisionRequest, timeout: float) -> TargetResult:
        def failed(error: ResultError, warnings: list[ResultWarning] | None = None) -> TargetResult:
            # Nothing was sent, so the result has no request body.
            return TargetResult(target=target.name, ok=False, error=error, warnings=warnings or [])

        provider = self._providers.get(target.name)
        if provider is None:
            return failed(ResultError(code="not_ready", message=self._missing_reason(target)))
        checked = self._health.get(target.name)
        if checked is not None and checked[0].reason:
            return failed(ResultError(code="not_ready", message=checked[0].reason))
        error, warnings = preflight(request, target)
        if error is not None:
            return failed(error, warnings)
        try:
            raw = await asyncio.wait_for(provider.decide(request, timeout=timeout), timeout + TIMEOUT_GRACE_S)
        except TimeoutError:
            raw = RawResult(
                request_body=request.system_one_body(target.model),
                error=ResultError(code="timeout", message=f"No response in {timeout:g} s."),
            )
        result = target_result(target.name, request, raw, target.capabilities)
        codes = {warning.code for warning in warnings}
        result.warnings = [
            *warnings,
            *(warning for warning in target_warnings(target) if warning.code not in codes),
            *result.warnings,
        ]
        return result

    async def decide(self, body: DecideBody) -> DecideResponse:
        """Send one request to each chosen target at once.

        Args:
            body: The state, the questions, and the targets.

        Returns:
            One result per target, in the order named. A target that isn't ready or fails preflight has a result
            with `ok: false`.

        Raises:
            UnknownTargetError: A target name isn't in the config.
        """
        targets = self.resolve_targets(body.targets)
        request = DecisionRequest(state=body.state, questions=body.questions, images=body.images)
        timeout = body.timeout_s or self.config.defaults.timeout_s
        asked_at = self._clock()
        results = await asyncio.gather(*(self._decide_one(target, request, timeout) for target in targets))
        return DecideResponse(
            request=request,
            question_set_version=QuestionSet(name="decide", questions=request.questions).version,
            asked_at=asked_at,
            results=list(results),
        )
