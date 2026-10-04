"""Versioned observations and private execution state, with one SQLite writer."""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json

from sqlalchemy import select, update, delete
from sqlalchemy.dialects.sqlite import insert

from .database import Database
from .migrate import upgrade_database
from .schema import runs, stages, observations, artifacts
from .models import canonical, digest, validate_record

SOURCES = ("catalog", "madgrades", "enrollment", "instructors", "buildings")
STAGES = SOURCES
KINDS = (
    "subjects",
    "courses",
    "terms",
    "grades",
    "offerings",
    "instructors",
    "faculty",
    "ratings",
    "buildings",
)


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root, readonly=False):
        self.root = Path(root).resolve()
        if not readonly:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = Database(self.root / "pipeline.sqlite", readonly=readonly, wal=True)
        if not readonly:
            try:
                upgrade_database(self.db, "pipeline")
            except Exception:
                self.db.close()
                raise

    def close(self):
        self.db.close()

    def new_run(self, semester, config):
        run = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        with self.db:
            self.db.execute(
                insert(runs).values(
                    run_id=run,
                    semester=semester,
                    started_at=now(),
                    status="pending",
                    config_json=canonical(config),
                    observed_at=now(),
                )
            )
            self.db.executemany(
                insert(stages),
                [
                    {
                        "run_id": run,
                        "stage": stage,
                        "status": "pending",
                        "error": None,
                        "updated_at": now(),
                    }
                    for stage in STAGES
                ],
            )
        return run

    def run(self, run):
        row = self.db.execute(select(runs).where(runs.c.run_id == run)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run: {run}")
        return dict(row)

    def stage_status(self, run, stage):
        row = self.db.execute(
            select(stages.c.status).where(
                stages.c.run_id == run, stages.c.stage == stage
            )
        ).fetchone()
        return row[0] if row else None

    def stage(self, run, stage, status, error=None):
        with self.db:
            self.db.execute(
                update(stages)
                .where(stages.c.run_id == run, stages.c.stage == stage)
                .values(status=status, error=error, updated_at=now())
            )

    def mutable(self, run):
        if self.run(run)["status"] == "complete":
            raise ValueError("Completed runs are immutable")

    def reset_source(self, run, source):
        self.mutable(run)
        with self.db:
            self.db.execute(
                delete(observations).where(
                    observations.c.run_id == run, observations.c.source == source
                )
            )

    def put(self, run, source, item):
        self.mutable(run)
        record = validate_record(item)
        with self.db:
            statement = insert(observations).values(
                run_id=run,
                source=source,
                kind=record.kind,
                entity_id=record.key,
                source_url=record.source_url,
                observed_at=now(),
                content_hash=digest(record.payload),
                payload_json=canonical(record.payload),
            )
            self.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        observations.c.run_id,
                        observations.c.source,
                        observations.c.kind,
                        observations.c.entity_id,
                    ],
                    set_={
                        name: statement.excluded[name]
                        for name in (
                            "source_url",
                            "content_hash",
                            "payload_json",
                            "observed_at",
                        )
                    },
                )
            )

    def records(self, run, kind, source=None):
        statement = (
            select(
                observations.c.entity_id,
                observations.c.source,
                observations.c.payload_json,
            )
            .where(observations.c.run_id == run, observations.c.kind == kind)
            .order_by(observations.c.entity_id, observations.c.source)
        )
        if source is not None:
            statement = statement.where(observations.c.source == source)
        records, owners = {}, {}
        # Preserve the historical Madgrades/enrollment term precedence explicitly.
        term_priority = {"legacy": 0, "enrollment": 1, "madgrades": 2}
        for row in self.db.execute(statement):
            key, owner, payload = row
            value = json.loads(payload)
            if key in records:
                previous = owners[key]
                if (
                    kind == "terms"
                    and owner in term_priority
                    and previous in term_priority
                ):
                    if term_priority[owner] <= term_priority[previous]:
                        continue
                elif records[key] != value:
                    raise ValueError(
                        f"Conflicting {kind} record {key!r} from {previous!r} and {owner!r}; select a source explicitly"
                    )
            records[key], owners[key] = value, owner
        return records

    def artifact(self, run, name, payload, inputs, config):
        self.mutable(run)
        with self.db:
            statement = insert(artifacts).values(
                run_id=run,
                name=name,
                input_hash=inputs,
                config_json=canonical(config),
                payload_json=canonical(payload),
            )
            self.db.execute(
                statement.on_conflict_do_update(
                    index_elements=[artifacts.c.run_id, artifacts.c.name],
                    set_={
                        key: statement.excluded[key]
                        for key in ("input_hash", "config_json", "payload_json")
                    },
                )
            )

    def get_artifact(self, run, name):
        row = self.db.execute(
            select(artifacts.c.payload_json).where(
                artifacts.c.run_id == run, artifacts.c.name == name
            )
        ).fetchone()
        if row is None:
            raise ValueError(f"Missing artifact: {name}")
        return json.loads(row[0])

    def input_hash(self, run):
        return digest(
            [
                tuple(row)
                for row in self.db.execute(
                    select(
                        observations.c.source,
                        observations.c.kind,
                        observations.c.entity_id,
                        observations.c.content_hash,
                    )
                    .where(observations.c.run_id == run)
                    .order_by(
                        observations.c.source,
                        observations.c.kind,
                        observations.c.entity_id,
                    )
                )
            ]
        )

    def finish(self, run):
        with self.db:
            self.db.execute(
                update(runs)
                .where(runs.c.run_id == run)
                .values(status="complete", completed_at=now())
            )

    @contextmanager
    def lock(self):
        import fcntl

        with (self.root / "pipeline.lock").open("w") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    "Another pipeline command is writing this workspace"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
