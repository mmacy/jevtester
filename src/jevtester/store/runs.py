"""Runs, results, the result cache, and question set versions in SQLite.

The database lives at `.jevtester/runs.sqlite`, which git ignores. Each row keeps its model as JSON, so the schema
changes with the models and not with SQL migrations.

Each `RunStore` is an owner with a random token, and each run records the owner that started it. A file store holds an
exclusive lock on `<database>.owners/<token>.lock` while it's open. The operating system releases the lock when the
process ends, even after a crash, so a run whose owner's lock is free belongs to a process that has gone.
"""

import fcntl
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from jevtester.model import Model
from jevtester.normalize import TargetResult
from jevtester.schemas import RunSummary
from jevtester.spec import Case, QuestionSet
from jevtester.spec.policy import Policy

_SCHEMA = """
create table if not exists runs (
    id text primary key,
    created_at text not null,
    summary text not null
);
create table if not exists results (
    run_id text not null,
    seq integer not null,
    case_id text not null,
    target text not null,
    repeat integer not null,
    variant text not null,
    cached integer not null,
    result text not null,
    primary key (run_id, case_id, target, repeat, variant)
);
create table if not exists cache (
    key text primary key,
    target text not null,
    created_at text not null,
    result text not null
);
create table if not exists run_cases (
    run_id text primary key,
    cases text not null
);
create table if not exists run_owners (
    run_id text primary key,
    owner text not null
);
create table if not exists run_policies (
    run_id text primary key,
    policy text not null
);
create table if not exists question_set_versions (
    name text not null,
    version text not null,
    first_seen text not null,
    question_set text not null,
    primary key (name, version)
);
"""


_CASES = TypeAdapter(list[Case])
_ACTIVE = ("queued", "running")


class StoredResult(Model):
    """One job's result in a run."""

    case_id: str
    target: str
    repeat: int
    variant: str | None = None
    cached: bool
    result: TargetResult


class StoredVersion(Model):
    """A question set version, and when jevtester first saw it."""

    question_set: QuestionSet
    first_seen: datetime


class RunStore:
    """The SQLite database for one jevtester directory."""

    def __init__(self, path: Path) -> None:
        """Open the database, creating it and its tables if needed.

        Args:
            path: The database file. `:memory:` keeps it in memory, for tests.
        """
        self.owner = uuid.uuid4().hex
        """This store's owner token. Runs this store creates record it."""
        self._owners: Path | None = None
        self._owner_fd: int | None = None
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
            self._owners = path.with_name(f"{path.name}.owners")
            self._owners.mkdir(exist_ok=True)
            # Lock the file before it gets its .lock name, so no other store sees it unlocked and takes it for a
            # dead owner's.
            pending = self._owners / f"{self.owner}.pending"
            self._owner_fd = os.open(pending, os.O_RDWR | os.O_CREAT, 0o644)
            fcntl.flock(self._owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            pending.rename(self._owners / f"{self.owner}.lock")
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the database and release this store's owner lock."""
        self._db.close()
        if self._owners is not None and self._owner_fd is not None:
            (self._owners / f"{self.owner}.lock").unlink(missing_ok=True)
            os.close(self._owner_fd)
            self._owner_fd = None

    # Owners

    def _live_owners(self) -> set[str]:
        # Every owner whose lock is held, and this store. Removes the lock files of owners that have gone.
        live = {self.owner}
        if self._owners is None:
            return live
        for lock in self._owners.glob("*.lock"):
            if lock.stem == self.owner:
                continue
            try:
                fd = os.open(lock, os.O_RDWR)
            except FileNotFoundError:
                continue
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                live.add(lock.stem)
            else:
                lock.unlink(missing_ok=True)
            finally:
                os.close(fd)
        return live

    def interrupted_runs(self) -> list[RunSummary]:
        """Find the queued and running runs whose owner has gone.

        A run's owner has gone when the process that started it has ended. A run with no recorded owner counts as
        interrupted. A run that another open store owns, in this process or another one, isn't interrupted.

        Returns:
            The runs, newest first.
        """
        live = self._live_owners()
        with self._lock:
            owners = dict(self._db.execute("select run_id, owner from run_owners").fetchall())
        return [run for run in self.list_runs() if run.status in _ACTIVE and owners.get(run.id) not in live]

    # Runs

    def next_run_id(self) -> str:
        """Return the next run id: the largest id plus one, as four or more digits."""
        with self._lock:
            row = self._db.execute("select max(cast(id as integer)) from runs").fetchone()
        return f"{(row[0] or 0) + 1:04d}"

    def create_run(self, summary: RunSummary) -> None:
        """Save a new run's summary, with this store as its owner.

        Args:
            summary: The run.
        """
        with self._lock, self._db:
            self._db.execute(
                "insert or replace into runs (id, created_at, summary) values (?, ?, ?)",
                (summary.id, summary.created_at.isoformat(), summary.model_dump_json()),
            )
            self._db.execute("insert or replace into run_owners values (?, ?)", (summary.id, self.owner))

    def save_run(self, summary: RunSummary) -> None:
        """Insert or replace a run's summary.

        Args:
            summary: The run.
        """
        with self._lock, self._db:
            self._db.execute(
                "insert or replace into runs (id, created_at, summary) values (?, ?, ?)",
                (summary.id, summary.created_at.isoformat(), summary.model_dump_json()),
            )

    def get_run(self, run_id: str) -> RunSummary | None:
        """Read a run's summary.

        Args:
            run_id: The run's id.

        Returns:
            The summary, or `None` when there's no such run.
        """
        with self._lock:
            row = self._db.execute("select summary from runs where id = ?", (run_id,)).fetchone()
        return RunSummary.model_validate_json(row[0]) if row else None

    def list_runs(self) -> list[RunSummary]:
        """Read every run's summary.

        Returns:
            The runs, newest first.
        """
        with self._lock:
            rows = self._db.execute("select summary from runs order by created_at desc, id desc").fetchall()
        return [RunSummary.model_validate_json(row[0]) for row in rows]

    def save_cases(self, run_id: str, cases: list[Case]) -> None:
        """Save the cases a run asks, so later edits to the suite don't change how the run is scored.

        Args:
            run_id: The run's id.
            cases: The cases.
        """
        with self._lock, self._db:
            self._db.execute(
                "insert or replace into run_cases values (?, ?)", (run_id, _CASES.dump_json(cases).decode())
            )

    def cases(self, run_id: str) -> list[Case] | None:
        """Read the cases a run asked.

        Args:
            run_id: The run's id.

        Returns:
            The cases, or `None` when the run has none saved.
        """
        with self._lock:
            row = self._db.execute("select cases from run_cases where run_id = ?", (run_id,)).fetchone()
        return _CASES.validate_json(row[0]) if row else None

    def save_policy(self, run_id: str, policy: Policy) -> None:
        """Save the policy a run's suite had when it started, so its decisions are measured with that policy.

        Args:
            run_id: The run's id.
            policy: The policy.
        """
        with self._lock, self._db:
            self._db.execute("insert or replace into run_policies values (?, ?)", (run_id, policy.model_dump_json()))

    def policy(self, run_id: str) -> Policy | None:
        """Read the policy a run was measured with.

        Args:
            run_id: The run's id.

        Returns:
            The policy, or `None` when the run's suite had none.
        """
        with self._lock:
            row = self._db.execute("select policy from run_policies where run_id = ?", (run_id,)).fetchone()
        return Policy.model_validate_json(row[0]) if row else None

    # Results

    def save_result(self, run_id: str, stored: StoredResult) -> None:
        """Save one job's result, in the order results arrive.

        Args:
            run_id: The run's id.
            stored: The job and its result.
        """
        with self._lock, self._db:
            seq = self._db.execute("select count(*) from results where run_id = ?", (run_id,)).fetchone()[0]
            self._db.execute(
                "insert or replace into results values (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    seq,
                    stored.case_id,
                    stored.target,
                    stored.repeat,
                    stored.variant or "",
                    int(stored.cached),
                    stored.result.model_dump_json(),
                ),
            )

    def results(self, run_id: str) -> list[StoredResult]:
        """Read a run's results.

        Args:
            run_id: The run's id.

        Returns:
            The results, in the order they arrived.
        """
        with self._lock:
            rows = self._db.execute(
                "select case_id, target, repeat, variant, cached, result from results where run_id = ? order by seq",
                (run_id,),
            ).fetchall()
        return [
            StoredResult(
                case_id=case_id,
                target=target,
                repeat=repeat,
                variant=variant or None,
                cached=bool(cached),
                result=TargetResult.model_validate_json(result),
            )
            for case_id, target, repeat, variant, cached, result in rows
        ]

    # The cache

    def cache_get(self, key: str) -> TargetResult | None:
        """Look up a cached result.

        Args:
            key: The job's cache key.

        Returns:
            The result, or `None` on a miss.
        """
        with self._lock:
            row = self._db.execute("select result from cache where key = ?", (key,)).fetchone()
        return TargetResult.model_validate_json(row[0]) if row else None

    def cache_put(self, key: str, result: TargetResult, at: datetime) -> None:
        """Cache a result.

        Args:
            key: The job's cache key.
            result: The result.
            at: When it was made.
        """
        with self._lock, self._db:
            self._db.execute(
                "insert or replace into cache values (?, ?, ?, ?)",
                (key, result.target, at.isoformat(), result.model_dump_json()),
            )

    # Question set versions

    def record_version(self, question_set: QuestionSet, at: datetime) -> None:
        """Record a question set version the first time it's seen.

        Args:
            question_set: The question set.
            at: When it was seen.
        """
        with self._lock, self._db:
            self._db.execute(
                "insert or ignore into question_set_versions values (?, ?, ?, ?)",
                (question_set.name, question_set.version, at.isoformat(), question_set.model_dump_json()),
            )

    def versions(self, name: str) -> list[StoredVersion]:
        """Read every recorded version of a question set.

        Args:
            name: The question set's name.

        Returns:
            The versions, newest first.
        """
        with self._lock:
            rows = self._db.execute(
                "select question_set, first_seen from question_set_versions where name = ? "
                "order by first_seen desc, rowid desc",
                (name,),
            ).fetchall()
        return [
            StoredVersion(
                question_set=QuestionSet.model_validate_json(question_set),
                first_seen=datetime.fromisoformat(first_seen),
            )
            for question_set, first_seen in rows
        ]

    def get_version(self, name: str, version: str) -> StoredVersion | None:
        """Read one version of a question set.

        Args:
            name: The question set's name.
            version: The version hash, or a prefix of it at least 8 characters long.

        Returns:
            The version, or `None` when there's no such version or the prefix matches more than one.
        """
        if len(version) < 8:
            return None
        matches = [stored for stored in self.versions(name) if stored.question_set.version.startswith(version)]
        return matches[0] if len(matches) == 1 else None
