"""Run a suite's jobs: concurrency and rate limits, caching, progress events, and cancellation."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from jevtester.normalize import TargetResult
from jevtester.providers import DecisionProvider
from jevtester.runner.jobs import ask, cache_key
from jevtester.schemas import (
    ApiErrorBody,
    CancelledEvent,
    FinishedEvent,
    ProgressEvent,
    ResultEvent,
    RunCounts,
    RunErrorEvent,
    RunEvent,
    RunSummary,
    TargetCounts,
    TargetSkippedEvent,
)
from jevtester.spec import Case, DecisionRequest, Target
from jevtester.store.runs import RunStore, StoredResult

FINAL_EVENTS = {"finished", "cancelled", "error"}


@dataclass(frozen=True)
class Job:
    """One case on one target for one repeat."""

    case: Case
    target: Target
    repeat: int
    request: DecisionRequest
    variant: str | None = None


def final_event(summary: RunSummary) -> RunEvent | None:
    """Build the last event of a run that has ended.

    Args:
        summary: The run.

    Returns:
        The `finished`, `cancelled`, or `error` event, or `None` while the run is queued or running.
    """
    match summary.status:
        case "finished":
            return FinishedEvent(run_id=summary.id, counts=summary.counts, summary=summary)
        case "cancelled":
            return CancelledEvent(run_id=summary.id, counts=summary.counts, summary=summary)
        case "failed":
            error = summary.error or ApiErrorBody(code="internal", message="The run failed.")
            return RunErrorEvent(run_id=summary.id, error=error, counts=summary.counts, summary=summary)
        case "queued" | "running":
            return None


class RunHandle:
    """A run in progress in this process, and its events."""

    def __init__(self, summary: RunSummary) -> None:
        """Follow one run.

        Args:
            summary: The run as it starts.
        """
        self.summary = summary
        self.task: asyncio.Task[None] | None = None
        self._events: list[RunEvent] = []
        self._waiter = asyncio.Event()

    def publish(self, event: RunEvent) -> None:
        """Send an event to every subscriber.

        Args:
            event: The event.
        """
        self._events.append(event)
        waiter, self._waiter = self._waiter, asyncio.Event()
        waiter.set()

    async def subscribe(self) -> AsyncIterator[RunEvent]:
        """Follow the run from now on.

        Yields:
            A `progress` event with the current counts, then each event that follows, ending with the final one.
        """
        index = len(self._events)
        yield ProgressEvent(run_id=self.summary.id, status=self.summary.status, counts=self.summary.counts)
        final = final_event(self.summary)
        if final is not None:
            yield final
            return
        while True:
            while index < len(self._events):
                event = self._events[index]
                index += 1
                yield event
                if event.type in FINAL_EVENTS:
                    return
            await self._waiter.wait()


class _Pacer:
    """Spaces request starts to stay under a requests-per-minute limit."""

    def __init__(self, requests_per_minute: int) -> None:
        self._interval = 60 / requests_per_minute
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


class _Tally:
    """A run's counts and cost, updated as jobs finish."""

    def __init__(self, targets: list[str], jobs: Mapping[str, int]) -> None:
        self.rows = {
            target: TargetCounts(target=target, jobs=jobs.get(target, 0), sent=0, cached=0, failed=0, skipped=0)
            for target in targets
        }
        self.cost: float | None = None

    def counts(self) -> RunCounts:
        rows = list(self.rows.values())
        sent = sum(row.sent for row in rows)
        cached = sum(row.cached for row in rows)
        failed = sum(row.failed for row in rows)
        skipped = sum(row.skipped for row in rows)
        return RunCounts(
            jobs=sum(row.jobs for row in rows),
            done=sent + cached + failed + skipped,
            sent=sent,
            cached=cached,
            failed=failed,
            skipped=skipped,
            targets=[row.model_copy() for row in rows],
        )

    def add(self, result: TargetResult, cached: bool) -> None:
        row = self.rows[result.target]
        if cached:
            row.cached += 1
        elif result.ok:
            row.sent += 1
        else:
            row.failed += 1
        if cached:
            # A cached result costs nothing.
            self.cost = self.cost or 0.0
        elif result.cost_usd is not None:
            self.cost = (self.cost or 0.0) + result.cost_usd

    def skip(self, target: str, reason: str) -> None:
        row = self.rows[target]
        row.skipped = row.jobs
        row.skip_reason = reason


class Runner:
    """Runs jobs for every run in this process, sharing concurrency limits across runs."""

    def __init__(self, store: RunStore, clock: Callable[[], datetime]) -> None:
        """Run jobs and record them.

        Args:
            store: Where runs, results, and the cache are saved.
            clock: The current time.
        """
        self._store = store
        self._clock = clock
        self._limits: dict[str, asyncio.Semaphore] = {}
        self._pacers: dict[str, _Pacer] = {}

    def _limit(self, target: Target) -> asyncio.Semaphore:
        # Targets that share a group, like the models of one MLX server, share one limit.
        key = target.capabilities.concurrency_group or target.name
        if key not in self._limits:
            self._limits[key] = asyncio.Semaphore(target.capabilities.concurrency)
        return self._limits[key]

    def _pacer(self, target: Target) -> _Pacer | None:
        rpm = target.capabilities.requests_per_minute
        if rpm is None:
            return None
        if target.name not in self._pacers:
            self._pacers[target.name] = _Pacer(rpm)
        return self._pacers[target.name]

    def _save(self, handle: RunHandle, tally: _Tally, **changes: object) -> None:
        handle.summary = handle.summary.model_copy(update={"counts": tally.counts(), "cost_usd": tally.cost, **changes})
        self._store.save_run(handle.summary)

    async def _job(
        self,
        handle: RunHandle,
        tally: _Tally,
        job: Job,
        provider: DecisionProvider,
        timeout: float,
        no_cache: bool,
    ) -> None:
        key = cache_key(job.target, job.request, job.repeat)
        result = None if no_cache else self._store.cache_get(key)
        cached = result is not None
        if result is None:
            async with self._limit(job.target):
                pacer = self._pacer(job.target)
                if pacer is not None:
                    await pacer.wait()
                result = await ask(job.target, provider, job.request, timeout)
            if result.ok:
                self._store.cache_put(key, result, self._clock())
        stored = StoredResult(
            case_id=job.case.id,
            target=job.target.name,
            repeat=job.repeat,
            variant=job.variant,
            cached=cached,
            result=result,
        )
        self._store.save_result(handle.summary.id, stored)
        tally.add(result, cached)
        self._save(handle, tally)
        handle.publish(
            ResultEvent(
                run_id=handle.summary.id,
                case_id=job.case.id,
                target=job.target.name,
                repeat=job.repeat,
                variant=job.variant,
                cached=cached,
                result=result.model_copy(update={"request_body": None, "raw": None}),
                counts=handle.summary.counts,
            )
        )

    async def execute(
        self,
        handle: RunHandle,
        jobs: list[Job],
        providers: Mapping[str, DecisionProvider],
        skipped: Mapping[str, str],
        *,
        timeout: float,
        no_cache: bool,
    ) -> None:
        """Run every job, publishing an event for each, and record the run's outcome.

        Args:
            handle: The run.
            jobs: Every job in the run, including those of skipped targets.
            providers: Providers keyed by target name.
            skipped: Targets whose jobs are skipped, with the reason.
            timeout: Seconds to wait for each request.
            no_cache: Send every request, even when a cached result exists.
        """
        per_target: dict[str, int] = {}
        for job in jobs:
            per_target[job.target.name] = per_target.get(job.target.name, 0) + 1
        tally = _Tally(handle.summary.targets, per_target)
        self._save(handle, tally, status="running", started_at=self._clock())
        handle.publish(ProgressEvent(run_id=handle.summary.id, status="running", counts=handle.summary.counts))
        tasks: list[asyncio.Task[None]] = []
        try:
            for target, reason in skipped.items():
                tally.skip(target, reason)
                self._save(handle, tally)
                handle.publish(
                    TargetSkippedEvent(
                        run_id=handle.summary.id, target=target, reason=reason, counts=handle.summary.counts
                    )
                )
            for job in jobs:
                if job.target.name in skipped:
                    continue
                provider = providers[job.target.name]
                tasks.append(asyncio.create_task(self._job(handle, tally, job, provider, timeout, no_cache)))
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._save(handle, tally, status="cancelled", finished_at=self._clock())
            handle.publish(
                CancelledEvent(run_id=handle.summary.id, counts=handle.summary.counts, summary=handle.summary)
            )
            return
        except Exception as error:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            body = ApiErrorBody(code="internal", message=f"{type(error).__name__}: {error}")
            self._save(handle, tally, status="failed", finished_at=self._clock(), error=body)
            handle.publish(
                RunErrorEvent(
                    run_id=handle.summary.id, error=body, counts=handle.summary.counts, summary=handle.summary
                )
            )
            return
        self._save(handle, tally, status="finished", finished_at=self._clock())
        handle.publish(FinishedEvent(run_id=handle.summary.id, counts=handle.summary.counts, summary=handle.summary))
