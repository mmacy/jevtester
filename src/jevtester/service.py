"""The operations the CLI and the API both call.

Each operation takes and returns the models in [`jevtester.schemas`][jevtester.schemas], so the CLI's JSON output
and the API's responses are the same.
"""

import asyncio
import math
import os
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from jevtester.credentials import AzureCliToken, WranglerToken
from jevtester.diff import diff_question_sets
from jevtester.errors import ConflictError, InvalidRequestError, NotFoundError
from jevtester.evaluate.checks import case_errors, wording_checks
from jevtester.evaluate.metrics import calibration, confusion_matrix, originals, run_changes, run_metrics
from jevtester.evaluate.probes import make_variants, probe_report
from jevtester.evaluate.report import report_markdown
from jevtester.evaluate.scoring import is_correct
from jevtester.normalize import ResultError, TargetResult
from jevtester.policy.engine import decide_result, decision_metrics, sweep
from jevtester.preflight import target_warnings
from jevtester.providers import DecisionProvider, Health
from jevtester.providers.systemone import SystemOneProvider
from jevtester.providers.workers_ai import WorkersAIProvider
from jevtester.runner.jobs import ask, not_sent
from jevtester.runner.run import Job, RunHandle, Runner, final_event
from jevtester.schemas import (
    ApiErrorBody,
    Calibration,
    CaseCreated,
    CaseResult,
    ConfusionMatrix,
    DecideBody,
    DecideResponse,
    ErrorDetail,
    PolicyBody,
    PolicyDetail,
    PolicyList,
    PolicySummary,
    PolicyThreshold,
    ProbeCreate,
    ProbeReport,
    ProbeVariant,
    ProgressEvent,
    QuestionSetBody,
    QuestionSetDetail,
    QuestionSetDiff,
    QuestionSetList,
    QuestionSetSummary,
    QuestionSetVersion,
    QuestionSetVersions,
    Regression,
    RunCase,
    RunChanges,
    RunComparison,
    RunCounts,
    RunCreate,
    RunCreated,
    RunEvent,
    RunKind,
    RunList,
    RunMetrics,
    RunReport,
    RunSummary,
    SuiteCheck,
    SuiteDetail,
    SuiteList,
    SuiteSummary,
    SweepBody,
    SweepResult,
    TargetCounts,
    TargetInfo,
    TargetList,
    TargetStatus,
)
from jevtester.spec import (
    Case,
    ChoiceQuestion,
    Config,
    DecisionRequest,
    Question,
    QuestionSet,
    ScoreQuestion,
    Suite,
    Target,
    load_config,
)
from jevtester.spec.policy import Policy
from jevtester.store.files import SuiteFiles, check_name
from jevtester.store.runs import RunStore, StoredResult

CONFIG_ENV = "JEVTESTER_CONFIG"
"""An environment variable naming the config file. Without it, jevtester reads `jevtester.toml` here."""
HEALTH_CHECK_TIMEOUT_S = 15.0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
INTERRUPTED = "The server stopped during the run"
MAX_SWEEP_POINTS = 1000


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
    wrangler = WranglerToken()
    providers: dict[str, DecisionProvider] = {}
    for target in config.targets.values():
        match target.provider:
            case "systemone":
                credential = azure if target.auth == "azure-cli" else None
                providers[target.name] = SystemOneProvider(target, credential)
            case "workers-ai":
                providers[target.name] = WorkersAIProvider(target, config.cloudflare.account_id, wrangler)
            case "claude":
                pass
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
        files: SuiteFiles | None = None,
        store: RunStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Serve one config.

        Args:
            config: The targets and defaults.
            providers: A provider for each target that has one, keyed by target name.
            files: The suites and question sets. `None` reads `suites/` in the working directory.
            store: The run database. `None` keeps runs in memory.
            clock: The current time, for tests.
        """
        self.config = config
        self.files = files or SuiteFiles(Path(config.paths.suites))
        self.store = store or RunStore(Path(":memory:"))
        self._providers = dict(providers)
        self._clock = clock
        self._health: dict[str, tuple[Health, datetime]] = {}
        self._checked_at: datetime | None = None
        self._runner = Runner(self.store, clock)
        self._handles: dict[str, RunHandle] = {}
        self._fail_interrupted_runs()

    @classmethod
    def load(cls, path: Path | None = None) -> Service:
        """Load the config and build its providers.

        Args:
            path: The config file. `None` uses [`config_path`][jevtester.service.config_path].

        Returns:
            The service.
        """
        path = path or config_path()
        config = load_config(path)
        root = path.parent
        files = SuiteFiles(root / config.paths.suites)
        store = RunStore(root / config.paths.store)
        return cls(config, build_providers(config), files=files, store=store)

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
            InvalidRequestError: A name isn't in the config, or is given twice.
        """
        if names == ["all"]:
            return list(self.config.targets.values())
        chosen = names or self.config.defaults.targets
        targets: list[Target] = []
        for index, name in enumerate(chosen):
            target = self.config.targets.get(name)
            if target is None:
                raise InvalidRequestError(f"Unknown target: {name}", field=f"targets.{index}")
            if target in targets:
                raise InvalidRequestError(f"{name} is named twice", field=f"targets.{index}")
            targets.append(target)
        return targets

    # Decide

    def _not_ready(self, target: Target) -> str | None:
        if target.name not in self._providers:
            return self._missing_reason(target)
        checked = self._health.get(target.name)
        return checked[0].reason if checked is not None else None

    async def _decide_one(self, target: Target, request: DecisionRequest, timeout: float) -> TargetResult:
        reason = self._not_ready(target)
        if reason is not None:
            return not_sent(target, ResultError(code="not_ready", message=reason))
        return await ask(target, self._providers[target.name], request, timeout)

    async def decide(self, body: DecideBody) -> DecideResponse:
        """Send one request to each chosen target at once.

        Args:
            body: The state, the questions, and the targets.

        Returns:
            One result per target, in the order named. A target that isn't ready or fails preflight has a result
            with `ok: false`.

        Raises:
            InvalidRequestError: A target name isn't in the config, or is given twice.
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

    # Suites

    def _record(self, question_set: QuestionSet) -> QuestionSet:
        self.store.record_version(question_set, self._clock())
        return question_set

    def _suites_using(self, question_set: str) -> list[str]:
        return [suite.name for suite in self.files.list_suites() if suite.question_set == question_set]

    def list_suites(self) -> SuiteList:
        """List the suites.

        Returns:
            Each suite with its question set's current version and its case counts.

        Raises:
            InvalidRequestError: A suite file is invalid.
        """
        summaries: list[SuiteSummary] = []
        for suite in self.files.list_suites():
            try:
                version: str | None = self._record(self.files.load_question_set(suite.question_set)).version
            except NotFoundError:
                version = None
            drafts = sum(1 for case in suite.cases if case.provenance != "human")
            summaries.append(
                SuiteSummary(
                    name=suite.name,
                    question_set=suite.question_set,
                    question_set_version=version,
                    policy=suite.policy,
                    targets=suite.targets,
                    case_count=len(suite.cases) - drafts,
                    draft_count=drafts,
                )
            )
        return SuiteList(suites=summaries)

    def get_suite(self, name: str) -> SuiteDetail:
        """Read a suite and its question set.

        Args:
            name: The suite's name.

        Returns:
            The suite, with its question set's current version.

        Raises:
            NotFoundError: There's no such suite, or its question set is missing.
            InvalidRequestError: A file is invalid.
        """
        suite = self.files.load_suite(name)
        return SuiteDetail(suite=suite, question_set=self._record(self.files.load_question_set(suite.question_set)))

    def check_suite(self, name: str) -> SuiteCheck:
        """Validate a suite and run the wording checks on its question set.

        Args:
            name: The suite's name.

        Returns:
            Whether the suite and its question set load and its cases fit the questions, with each error, and the
            wording findings.

        Raises:
            NotFoundError: There's no such suite.
        """
        try:
            suite = self.files.load_suite(name)
        except InvalidRequestError as error:
            return SuiteCheck(suite=name, valid=False, errors=[ErrorDetail(message=str(error))], checks=[])
        try:
            question_set = self.files.load_question_set(suite.question_set)
        except (NotFoundError, InvalidRequestError) as error:
            return SuiteCheck(
                suite=name, valid=False, errors=[ErrorDetail(field="question_set", message=str(error))], checks=[]
            )
        errors = case_errors(suite, question_set)
        if suite.policy:
            try:
                policy = self.files.load_policy(suite.policy)[0]
            except (NotFoundError, InvalidRequestError) as error:
                errors.append(ErrorDetail(field="policy", message=str(error)))
            else:
                missing = sorted(policy.questions() - set(question_set.questions))
                errors += [
                    ErrorDetail(field="policy", message=f"The policy reads {key}, which the question set doesn't ask")
                    for key in missing
                ]
        return SuiteCheck(suite=name, valid=not errors, errors=errors, checks=wording_checks(question_set))

    def add_case(self, name: str, case: Case) -> CaseCreated:
        """Add a case to the end of a suite's file.

        Args:
            name: The suite's name.
            case: The case.

        Returns:
            The case and the suite's new case count.

        Raises:
            NotFoundError: There's no such suite.
            ConflictError: The suite already has a case with that id.
        """
        suite = self.files.load_suite(name)
        if any(existing.id == case.id for existing in suite.cases):
            raise ConflictError(f"The suite already has a case {case.id}", field="id")
        suite = suite.model_copy(update={"cases": [*suite.cases, case]})
        self.files.save_suite(suite)
        return CaseCreated(suite=name, case=case, case_count=sum(1 for c in suite.cases if c.provenance == "human"))

    # Question sets

    def _question_set_detail(self, question_set: QuestionSet) -> QuestionSetDetail:
        return QuestionSetDetail(
            question_set=question_set,
            suites=self._suites_using(question_set.name),
            checks=wording_checks(question_set),
        )

    def list_question_sets(self) -> QuestionSetList:
        """List the question sets.

        Returns:
            Each question set's current version, question count, and the suites that use it.
        """
        summaries: list[QuestionSetSummary] = []
        for question_set in self.files.list_question_sets():
            self._record(question_set)
            stored = self.store.get_version(question_set.name, question_set.version)
            summaries.append(
                QuestionSetSummary(
                    name=question_set.name,
                    version=question_set.version,
                    question_count=len(question_set.questions),
                    suites=self._suites_using(question_set.name),
                    updated_at=stored.first_seen if stored else None,
                )
            )
        return QuestionSetList(question_sets=summaries)

    def get_question_set(self, name: str) -> QuestionSetDetail:
        """Read a question set's current version.

        Args:
            name: The question set's name.

        Returns:
            The question set, the suites that use it, and its wording checks.

        Raises:
            NotFoundError: There's no such question set.
        """
        return self._question_set_detail(self._record(self.files.load_question_set(name)))

    def save_question_set(self, name: str, body: QuestionSetBody) -> QuestionSetDetail:
        """Save new questions as a question set's current version, creating the set if it's new.

        Args:
            name: The question set's name.
            body: The questions.

        Returns:
            The saved question set.
        """
        question_set = QuestionSet(name=check_name(name, "question set"), questions=body.questions)
        self.files.save_question_set(question_set)
        return self._question_set_detail(self._record(question_set))

    def question_set_versions(self, name: str) -> QuestionSetVersions:
        """List a question set's versions.

        Args:
            name: The question set's name.

        Returns:
            Every version jevtester has seen, newest first, with how many runs used each.

        Raises:
            NotFoundError: There's no such question set.
        """
        current = self._record(self.files.load_question_set(name))
        runs = [run for run in self.store.list_runs() if run.question_set == name]
        versions = [
            QuestionSetVersion(
                version=stored.question_set.version,
                first_seen=stored.first_seen,
                question_count=len(stored.question_set.questions),
                run_count=sum(1 for run in runs if run.question_set_version == stored.question_set.version),
                current=stored.question_set.version == current.version,
            )
            for stored in self.store.versions(name)
        ]
        return QuestionSetVersions(name=name, versions=versions)

    def question_set_version(self, name: str, version: str) -> QuestionSet:
        """Read one version of a question set.

        Args:
            name: The question set's name.
            version: The version hash, or a prefix of it at least 8 characters long.

        Returns:
            That version.

        Raises:
            NotFoundError: There's no such version, or the prefix matches more than one.
        """
        check_name(name, "question set")
        stored = self.store.get_version(name, version)
        if stored is None:
            raise NotFoundError(f"No version {version} of the question set {name}")
        return stored.question_set

    def diff_question_set(self, name: str, from_version: str, to_version: str) -> QuestionSetDiff:
        """Compare two versions of a question set.

        Args:
            name: The question set's name.
            from_version: The older version, or a prefix of it.
            to_version: The newer version, or a prefix of it.

        Returns:
            How each question changed.

        Raises:
            NotFoundError: A version doesn't exist.
        """
        return diff_question_sets(
            self.question_set_version(name, from_version), self.question_set_version(name, to_version)
        )

    # Runs

    def _fail_interrupted_runs(self) -> None:
        for run in self.store.list_runs():
            if run.status in ("queued", "running"):
                error = ApiErrorBody(code="internal", message=INTERRUPTED)
                self.store.save_run(
                    run.model_copy(update={"status": "failed", "error": error, "finished_at": self._clock()})
                )

    def _empty_counts(self, targets: list[Target], jobs: list[Job]) -> RunCounts:
        rows = [
            TargetCounts(
                target=target.name,
                jobs=sum(1 for job in jobs if job.target.name == target.name),
                sent=0,
                cached=0,
                failed=0,
                skipped=0,
            )
            for target in targets
        ]
        return RunCounts(jobs=len(jobs), done=0, sent=0, cached=0, failed=0, skipped=0, targets=rows)

    def _question_set_for(self, suite: Suite, version: str | None) -> QuestionSet:
        if version is None:
            return self._record(self.files.load_question_set(suite.question_set))
        try:
            return self.question_set_version(suite.question_set, version)
        except NotFoundError as error:
            raise NotFoundError(str(error), field="question_set_version") from error

    async def start_run(self, body: RunCreate) -> RunCreated:
        """Start a run of a suite. It runs in the background.

        Args:
            body: The suite, targets, question set version, repeats, and cache setting.

        Returns:
            The run's id.

        Raises:
            NotFoundError: The suite, the question set version, or the baseline run doesn't exist.
            InvalidRequestError: A target name is invalid.
        """
        if body.baseline is not None and self.store.get_run(body.baseline) is None:
            raise NotFoundError(f"No run {body.baseline}", field="baseline")
        return await self._start(
            "suite",
            body.suite,
            body.targets,
            body.question_set_version,
            repeats=body.repeats or self.config.defaults.repeats,
            probes=[],
            no_cache=body.no_cache,
            baseline=body.baseline,
        )

    async def start_probe(self, body: ProbeCreate) -> RunCreated:
        """Start a probe run: each case as written, and the variants each probe makes of it.

        Args:
            body: The suite, targets, probes, question set version, and cache setting.

        Returns:
            The run's id. `GET /api/runs/{id}/probes` reports it once it has results.

        Raises:
            NotFoundError: The suite or the question set version doesn't exist.
            InvalidRequestError: A target name is invalid.
        """
        probes = list(dict.fromkeys(body.variants))
        return await self._start(
            "probe",
            body.suite,
            body.targets,
            body.question_set_version,
            repeats=1,
            probes=probes,
            no_cache=body.no_cache,
        )

    async def _start(
        self,
        kind: RunKind,
        suite_name: str,
        target_names: list[str],
        question_set_version: str | None,
        *,
        repeats: int,
        probes: list[ProbeVariant],
        no_cache: bool,
        baseline: str | None = None,
    ) -> RunCreated:
        suite = self.files.load_suite(suite_name)
        question_set = self._question_set_for(suite, question_set_version)
        targets = self.resolve_targets(target_names or suite.targets)
        cases = [case for case in suite.cases if case.provenance == "human"]
        jobs: list[Job] = []
        for case in cases:
            for target in targets:
                request = DecisionRequest(state=case.state, questions=question_set.questions, images=case.images)
                jobs += [Job(case=case, target=target, repeat=repeat, request=request) for repeat in range(repeats)]
                jobs += [
                    Job(case=case, target=target, repeat=0, request=variant.request, variant=variant.id)
                    for variant in make_variants(case, question_set.questions, target, probes)
                ]
        policy = self.files.load_policy(suite.policy)[0] if suite.policy else None
        now = self._clock()
        summary = RunSummary(
            id=self.store.next_run_id(),
            kind=kind,
            suite=suite.name,
            question_set=question_set.name,
            question_set_version=question_set.version,
            policy=suite.policy,
            policy_version=policy.version if policy else None,
            targets=[target.name for target in targets],
            repeats=repeats,
            variants=probes,
            no_cache=no_cache,
            baseline=baseline,
            status="queued",
            case_count=len(cases),
            counts=self._empty_counts(targets, jobs),
            cost_usd=None,
            created_at=now,
            started_at=None,
            finished_at=None,
        )
        self.store.save_run(summary)
        self.store.save_cases(summary.id, cases)
        if policy is not None:
            self.store.save_policy(summary.id, policy)
        handle = RunHandle(summary)
        self._handles[summary.id] = handle
        handle.task = asyncio.create_task(self._execute(handle, targets, jobs, no_cache=no_cache))
        return RunCreated(id=summary.id)

    async def _execute(self, handle: RunHandle, targets: list[Target], jobs: list[Job], *, no_cache: bool) -> None:
        # Check the targets first, so a target that's down is skipped instead of failing every job.
        healths = await asyncio.gather(*(self._check(target) for target in targets))
        now = self._clock()
        for target, health in zip(targets, healths, strict=True):
            self._health[target.name] = (health, now)
        skipped = {target.name: health.reason for target, health in zip(targets, healths, strict=True) if health.reason}
        await self._runner.execute(
            handle, jobs, self._providers, skipped, timeout=self.config.defaults.timeout_s, no_cache=no_cache
        )

    def list_runs(self) -> RunList:
        """List the runs.

        Returns:
            Every run, newest first.
        """
        return RunList(runs=self.store.list_runs())

    def get_run(self, run_id: str) -> RunSummary:
        """Read a run's summary.

        Args:
            run_id: The run's id.

        Returns:
            The run's settings, status, and counts.

        Raises:
            NotFoundError: There's no such run.
        """
        handle = self._handles.get(run_id)
        if handle is not None:
            return handle.summary
        summary = self.store.get_run(run_id)
        if summary is None:
            raise NotFoundError(f"No run {run_id}")
        return summary

    async def wait_run(self, run_id: str) -> RunSummary:
        """Wait for a run in this process to end.

        Args:
            run_id: The run's id.

        Returns:
            The run's final summary.
        """
        handle = self._handles.get(run_id)
        if handle is not None and handle.task is not None:
            await handle.task
        return self.get_run(run_id)

    async def run_events(self, run_id: str) -> AsyncIterator[RunEvent]:
        """Follow a run's events.

        Args:
            run_id: The run's id.

        Yields:
            A `progress` event with the current counts, then each event that follows. A run that has ended sends
            `progress` and its final event.

        Raises:
            NotFoundError: There's no such run.
        """
        handle = self._handles.get(run_id)
        if handle is not None:
            async for event in handle.subscribe():
                yield event
            return
        summary = self.get_run(run_id)
        yield ProgressEvent(run_id=run_id, status=summary.status, counts=summary.counts)
        final = final_event(summary)
        if final is not None:
            yield final

    async def cancel_run(self, run_id: str) -> RunSummary:
        """Cancel a queued or running run.

        Args:
            run_id: The run's id.

        Returns:
            The run's summary. A run that has ended is returned unchanged.

        Raises:
            NotFoundError: There's no such run.
        """
        handle = self._handles.get(run_id)
        if handle is not None and handle.task is not None and not handle.task.done():
            handle.task.cancel()
            await asyncio.gather(handle.task, return_exceptions=True)
        return self.get_run(run_id)

    # Evaluation

    def _context(self, run_id: str) -> tuple[RunSummary, list[StoredResult], dict[str, Question], dict[str, Case]]:
        summary = self.get_run(run_id)
        stored = self.store.get_version(summary.question_set, summary.question_set_version)
        if stored is None:
            raise NotFoundError(f"Run {run_id} used a question set version jevtester has no record of")
        cases = self.store.cases(run_id)
        if cases is None:
            # Runs saved before jevtester kept each run's cases are scored against the suite as it is now.
            cases = [case for case in self.files.load_suite(summary.suite).cases if case.provenance == "human"]
        return summary, self.store.results(run_id), dict(stored.question_set.questions), {c.id: c for c in cases}

    def _question(self, questions: dict[str, Question], question_id: str) -> Question:
        question = questions.get(question_id)
        if question is None:
            raise InvalidRequestError(f"The run didn't ask {question_id}", field="question")
        return question

    def _run_target(self, summary: RunSummary, target: str) -> str:
        if target not in summary.targets:
            raise InvalidRequestError(f"Run {summary.id} didn't run {target}", field="target")
        return target

    def run_metrics(self, run_id: str) -> RunMetrics:
        """Compute a run's metrics for each target and question.

        Args:
            run_id: The run's id.

        Returns:
            The metrics.

        Raises:
            NotFoundError: There's no such run.
        """
        summary, results, questions, cases = self._context(run_id)
        metrics = run_metrics(summary, results, questions, cases, self.config.targets)
        policy = self.store.policy(run_id)
        if policy is not None:
            for target in metrics.targets:
                if target.results:
                    target.decision = decision_metrics(policy, questions, originals(results, target.target), cases)
        return metrics

    def run_confusion(self, run_id: str, question: str, target: str) -> ConfusionMatrix:
        """Build the confusion matrix for one choice question and one target.

        Args:
            run_id: The run's id.
            question: A choice question's id.
            target: A target the run ran.

        Returns:
            Expected options against answered options.

        Raises:
            NotFoundError: There's no such run.
            InvalidRequestError: The question isn't a choice the run asked, or the run didn't run the target.
        """
        summary, results, questions, cases = self._context(run_id)
        found = self._question(questions, question)
        if not isinstance(found, ChoiceQuestion):
            raise InvalidRequestError(f"{question} is a {found.type} question, not a choice", field="question")
        return confusion_matrix(run_id, self._run_target(summary, target), question, found, results, cases)

    def run_calibration(self, run_id: str, question: str, target: str, bins: int) -> Calibration:
        """Build a reliability table for one noul or choice question and one target.

        Args:
            run_id: The run's id.
            question: A noul or choice question's id.
            target: A target the run ran.
            bins: The number of probability bins.

        Returns:
            The bins and the expected calibration error.

        Raises:
            NotFoundError: There's no such run.
            InvalidRequestError: The question is a score or isn't asked, the run didn't run the target, or `bins` is
                out of range.
        """
        if not 1 <= bins <= 100:
            raise InvalidRequestError("bins must be 1 to 100", field="bins")
        summary, results, questions, cases = self._context(run_id)
        found = self._question(questions, question)
        if isinstance(found, ScoreQuestion):
            raise InvalidRequestError(f"{question} is a score question, which has no calibration", field="question")
        return calibration(run_id, self._run_target(summary, target), question, found, results, cases, bins)

    def run_changes(self, run_id: str, baseline: str) -> RunChanges:
        """List the answers that changed from a baseline run.

        Args:
            run_id: The run's id.
            baseline: The baseline run's id.

        Returns:
            The changed answers, with McNemar's test for each target both runs ran.

        Raises:
            NotFoundError: Either run doesn't exist.
        """
        summary, results, questions, cases = self._context(run_id)
        try:
            before = self.get_run(baseline)
        except NotFoundError as error:
            raise NotFoundError(str(error), field="baseline") from error
        return run_changes(summary, before, results, self.store.results(baseline), cases, questions)

    def compare_runs(self, run_id: str, baseline: str, max_drop: float | None = None) -> RunComparison:
        """Compare a run with a baseline: both runs' metrics, the changed answers, and any regressions.

        Args:
            run_id: The run's id.
            baseline: The baseline run's id.
            max_drop: The largest allowed drop in accuracy. `None` uses the config's `defaults.max_drop`.

        Returns:
            The comparison. A regression is a target and question whose accuracy (within-tolerance accuracy, for a
            score) dropped by more than `max_drop`.

        Raises:
            NotFoundError: Either run doesn't exist.
        """
        allowed = self.config.defaults.max_drop if max_drop is None else max_drop
        now, before = self.run_metrics(run_id), self.run_metrics(baseline)
        regressions: list[Regression] = []
        for target in now.targets:
            old = next((t for t in before.targets if t.target == target.target), None)
            if old is None:
                continue
            for question in target.questions:
                previous = next((q for q in old.questions if q.question == question.question), None)
                if previous is None:
                    continue
                metric: Literal["accuracy", "within_tolerance"] = (
                    "within_tolerance" if question.type == "score" else "accuracy"
                )
                value, base = getattr(question, metric), getattr(previous, metric)
                if isinstance(value, float) and isinstance(base, float) and base - value > allowed:
                    regressions.append(
                        Regression(
                            target=target.target,
                            question=question.question,
                            metric=metric,
                            baseline=base,
                            value=value,
                            drop=base - value,
                        )
                    )
        return RunComparison(
            run_metrics=now,
            baseline_metrics=before,
            changes=self.run_changes(run_id, baseline),
            max_drop=allowed,
            regressions=regressions,
        )

    def run_case(self, run_id: str, case_id: str) -> RunCase:
        """Return one case in a run with every target's full result.

        Args:
            run_id: The run's id.
            case_id: The case's id.

        Returns:
            The case, the questions, and each result with whether each answer met its expectation.

        Raises:
            NotFoundError: There's no such run, or the run has no such case.
        """
        _, results, questions, cases = self._context(run_id)
        policy = self.store.policy(run_id)
        case = cases.get(case_id)
        if case is None:
            raise NotFoundError(f"Run {run_id} has no case {case_id}")
        rows = [
            CaseResult(
                target=stored.target,
                repeat=stored.repeat,
                variant=stored.variant,
                cached=stored.cached,
                correct={key: is_correct(case.expected.get(key), stored.result.answers.get(key)) for key in questions},
                decision=decide_result(policy, questions, stored.result) if policy else None,
                result=stored.result,
            )
            for stored in results
            if stored.case_id == case_id
        ]
        return RunCase(run_id=run_id, case=case, questions=questions, results=rows)

    def run_report(self, run_id: str) -> RunReport:
        """Report a run's summary and metrics, with its changes from its baseline when it has one.

        Args:
            run_id: The run's id.

        Returns:
            The summary, the metrics, and the same report as Markdown.

        Raises:
            NotFoundError: There's no such run.
        """
        summary = self.get_run(run_id)
        metrics = self.run_metrics(run_id)
        changes = self.run_changes(run_id, summary.baseline) if summary.baseline else None
        return RunReport(summary=summary, metrics=metrics, markdown=report_markdown(summary, metrics, changes))

    # Policies

    def _policy_suites(self, name: str) -> list[str]:
        return [suite.name for suite in self.files.list_suites() if suite.policy == name]

    def _policy_detail(self, policy: Policy, text: str) -> PolicyDetail:
        thresholds = [
            PolicyThreshold(
                name=name,
                value=value,
                per_target={target: values[name] for target, values in policy.per_target.items() if name in values},
            )
            for name, value in policy.thresholds.items()
        ]
        return PolicyDetail(
            name=policy.name,
            version=policy.version,
            yaml=text,
            actions=policy.actions,
            thresholds=thresholds,
            suites=self._policy_suites(policy.name),
        )

    def list_policies(self) -> PolicyList:
        """List the policies.

        Returns:
            Each policy's version, actions, and the suites that use it.

        Raises:
            InvalidRequestError: A policy file is invalid.
        """
        return PolicyList(
            policies=[
                PolicySummary(
                    name=policy.name,
                    version=policy.version,
                    actions=policy.actions,
                    suites=self._policy_suites(policy.name),
                )
                for policy, _ in self.files.list_policies()
            ]
        )

    def get_policy(self, name: str) -> PolicyDetail:
        """Read a policy.

        Args:
            name: The policy's name.

        Returns:
            Its YAML text, actions, thresholds, and the suites that use it.

        Raises:
            NotFoundError: There's no such policy.
        """
        return self._policy_detail(*self.files.load_policy(name))

    def save_policy(self, name: str, body: PolicyBody) -> PolicyDetail:
        """Validate and save a policy's YAML text, creating the policy if it's new.

        Args:
            name: The policy's name.
            body: The YAML text.

        Returns:
            The saved policy.

        Raises:
            InvalidRequestError: The YAML is invalid. `details` lists every error, and nothing is saved.
        """
        return self._policy_detail(self.files.save_policy(name, body.yaml), body.yaml)

    def sweep_policy(self, name: str, body: SweepBody) -> SweepResult:
        """Measure a target's decisions in a finished run as one of the policy's thresholds moves.

        The sweep uses the policy as it is now, so a threshold can be tuned against a run without running it again.
        Each swept value replaces the threshold for this target, whether the policy gives it a shared value or a
        `per_target` one. `current` is the target's value now.

        Args:
            name: The policy's name.
            body: The run, the target, the threshold, and the range to sweep.

        Returns:
            The share decided, the error rate, and the cost at each value.

        Raises:
            NotFoundError: The policy or the run doesn't exist.
            InvalidRequestError: The threshold isn't the policy's, the run didn't run the target, or the range has
                more than 1,000 points.
        """
        policy, _ = self.files.load_policy(name)
        if body.threshold not in policy.thresholds:
            raise InvalidRequestError(f"The policy has no threshold {body.threshold}", field="threshold")
        summary, results, questions, cases = self._context(body.run_id)
        target = self._run_target(summary, body.target)
        count = math.floor((body.stop - body.start) / body.step + 1e-9) + 1
        if count < 1 or count > MAX_SWEEP_POINTS:
            raise InvalidRequestError(f"The range gives {count} points; the limit is {MAX_SWEEP_POINTS}", field="step")
        values = [round(body.start + index * body.step, 10) for index in range(count)]
        points = sweep(policy, body.threshold, values, questions, originals(results, target), cases)
        return SweepResult(
            policy=name,
            run_id=summary.id,
            target=target,
            threshold=body.threshold,
            current=policy.threshold(body.threshold, target),
            points=points,
        )

    # Probes

    def run_probes(self, run_id: str) -> ProbeReport:
        """Report how often each case's answers changed under each probe.

        Args:
            run_id: A probe run's id.

        Returns:
            A cell for each case, target, and probe, and the change rate for each target and probe.

        Raises:
            NotFoundError: There's no such run.
            InvalidRequestError: The run isn't a probe run.
        """
        summary = self.get_run(run_id)
        if summary.kind != "probe":
            raise InvalidRequestError(f"Run {run_id} is a suite run, not a probe run")
        return probe_report(run_id, summary.variants, self.store.results(run_id))
