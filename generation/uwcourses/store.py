"""Versioned observations and private execution state, with one SQLite writer."""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json

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
        if readonly:
            self.db = sqlite3.connect(
                (self.root / "pipeline.sqlite").as_uri() + "?mode=ro", uri=True
            )
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA query_only=ON")
            return
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "pipeline.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.migrate()
        self.create_views()

    def close(self):
        self.db.close()

    def migrate(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 2:
            raise ValueError("Database schema is newer than this pipeline")
        if version == 2:
            return
        if version == 1:
            self.db.executescript("""
            BEGIN;
            ALTER TABLE runs ADD COLUMN observed_at TEXT;
            ALTER TABLE runs ADD COLUMN origin TEXT NOT NULL DEFAULT 'scrape';
            ALTER TABLE runs ADD COLUMN source_revision TEXT;
            UPDATE runs SET observed_at=started_at;
            DROP VIEW IF EXISTS current_observations;
            PRAGMA user_version=2;
            COMMIT;
            """)
            return
        self.db.executescript("""
        BEGIN;
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, semester TEXT NOT NULL, started_at TEXT NOT NULL,
            completed_at TEXT, status TEXT NOT NULL, config_json TEXT NOT NULL,
            revision TEXT
        );
        CREATE TABLE stages (
            run_id TEXT REFERENCES runs(run_id), stage TEXT, status TEXT NOT NULL,
            error TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(run_id, stage)
        );
        CREATE TABLE observations (
            run_id TEXT REFERENCES runs(run_id), source TEXT NOT NULL, kind TEXT NOT NULL,
            entity_id TEXT NOT NULL, source_url TEXT NOT NULL, observed_at TEXT NOT NULL,
            content_hash TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
            PRIMARY KEY(run_id, source, kind, entity_id)
        );
        CREATE INDEX observation_kind ON observations(run_id, kind);
        CREATE VIEW current_observations AS SELECT * FROM observations
            WHERE run_id=(SELECT run_id FROM runs WHERE status='complete'
                          ORDER BY completed_at DESC, run_id DESC LIMIT 1);
        CREATE TABLE responses (
            run_id TEXT REFERENCES runs(run_id), source TEXT, fingerprint TEXT,
            url TEXT NOT NULL, status INTEGER NOT NULL, content_type TEXT NOT NULL,
            body_hash TEXT NOT NULL, fetched_at TEXT NOT NULL,
            PRIMARY KEY(run_id, source, fingerprint)
        );
        CREATE TABLE artifacts (
            run_id TEXT REFERENCES runs(run_id), name TEXT, input_hash TEXT NOT NULL,
            config_json TEXT NOT NULL, payload_json TEXT NOT NULL,
            PRIMARY KEY(run_id, name)
        );
        PRAGMA user_version=1;
        COMMIT;
        """)
        self.migrate()

    def create_views(self):
        latest = "SELECT run_id FROM runs WHERE status='complete' ORDER BY observed_at DESC, (origin='scrape') DESC, run_id DESC LIMIT 1"
        self.db.execute("DROP VIEW IF EXISTS current_observations")
        self.db.execute(
            f"CREATE VIEW current_observations AS SELECT * FROM observations WHERE run_id=({latest})"
        )
        # Relational read interfaces over immutable, source-owned observations.
        projections = {
            "courses": "entity_id AS course_id, json_extract(payload_json,'$.course_reference.course_number') AS course_number, json_extract(payload_json,'$.course_title') AS title, json_extract(payload_json,'$.description') AS description, json_extract(payload_json,'$.prerequisites') AS prerequisites_json",
            "subjects": "entity_id AS subject_id, json_extract(payload_json,'$.name') AS name",
            "terms": "entity_id AS term_id, json_extract(payload_json,'$.name') AS name",
            "instructors": "entity_id AS instructor_id, json_extract(payload_json,'$.name') AS name, json_extract(payload_json,'$.email') AS email",
            "offerings": "entity_id AS offering_id, json_extract(payload_json,'$.term') AS term_id, json_extract(payload_json,'$.course_reference') AS course_reference_json, json_extract(payload_json,'$.sections') AS sections_json",
            "grades": "entity_id AS source_course_id, json_extract(payload_json,'$.course_reference') AS course_reference_json, json_extract(payload_json,'$.cumulative') AS cumulative_json, json_extract(payload_json,'$.courseOfferings') AS terms_json",
        }
        for kind, projection in projections.items():
            self.db.execute(
                f"CREATE VIEW IF NOT EXISTS {kind} AS SELECT run_id,source,source_url,observed_at,{projection} FROM observations WHERE kind='{kind}'"
            )
            self.db.execute(f"DROP VIEW IF EXISTS current_{kind}")
            self.db.execute(
                f"CREATE VIEW current_{kind} AS SELECT * FROM {kind} WHERE run_id=({latest})"
            )
        self.db.execute(
            "CREATE VIEW IF NOT EXISTS course_subjects AS SELECT o.run_id,o.entity_id AS course_id,j.value AS subject_id FROM observations o,json_each(o.payload_json,'$.course_reference.subjects') j WHERE o.kind='courses'"
        )
        self.db.commit()

    def new_run(self, semester, config):
        run = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        with self.db:
            self.db.execute(
                "INSERT INTO runs(run_id,semester,started_at,status,config_json,observed_at) VALUES(?,?,?,'pending',?,?)",
                (run, semester, now(), canonical(config), now()),
            )
            self.db.executemany(
                "INSERT INTO stages VALUES(?,?,'pending',NULL,?)",
                [(run, s, now()) for s in STAGES],
            )
        return run

    def run(self, run):
        row = self.db.execute("SELECT * FROM runs WHERE run_id=?", (run,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown run: {run}")
        return dict(row)

    def stage_status(self, run, stage):
        row = self.db.execute(
            "SELECT status FROM stages WHERE run_id=? AND stage=?", (run, stage)
        ).fetchone()
        return row[0] if row else None

    def stage(self, run, stage, status, error=None):
        with self.db:
            self.db.execute(
                "UPDATE stages SET status=?,error=?,updated_at=? WHERE run_id=? AND stage=?",
                (status, error, now(), run, stage),
            )

    def mutable(self, run):
        if self.run(run)["status"] == "complete":
            raise ValueError("Completed runs are immutable")

    def reset_source(self, run, source):
        self.mutable(run)
        with self.db:
            self.db.execute(
                "DELETE FROM observations WHERE run_id=? AND source=?", (run, source)
            )

    def put(self, run, source, item):
        self.mutable(run)
        record = validate_record(item)
        with self.db:
            self.db.execute(
                """INSERT INTO observations VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id,source,kind,entity_id) DO UPDATE SET
                source_url=excluded.source_url, content_hash=excluded.content_hash,
                payload_json=excluded.payload_json, observed_at=excluded.observed_at""",
                (
                    run,
                    source,
                    record.kind,
                    record.key,
                    record.source_url,
                    now(),
                    digest(record.payload),
                    canonical(record.payload),
                ),
            )

    def records(self, run, kind, source=None):
        sql = (
            "SELECT entity_id,payload_json FROM observations WHERE run_id=? AND kind=?"
        )
        params = [run, kind]
        if source:
            sql += " AND source=?"
            params.append(source)
        sql += " ORDER BY entity_id, source"
        return {r[0]: json.loads(r[1]) for r in self.db.execute(sql, params)}

    def artifact(self, run, name, payload, inputs, config):
        self.mutable(run)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO artifacts VALUES(?,?,?,?,?)",
                (run, name, inputs, canonical(config), canonical(payload)),
            )

    def get_artifact(self, run, name):
        row = self.db.execute(
            "SELECT payload_json FROM artifacts WHERE run_id=? AND name=?", (run, name)
        ).fetchone()
        if row is None:
            raise ValueError(f"Missing artifact: {name}")
        return json.loads(row[0])

    def input_hash(self, run):
        return digest(
            [
                tuple(r)
                for r in self.db.execute(
                    "SELECT source,kind,entity_id,content_hash FROM observations WHERE run_id=? ORDER BY source,kind,entity_id",
                    (run,),
                )
            ]
        )

    def finish(self, run):
        with self.db:
            self.db.execute(
                "UPDATE runs SET status='complete',completed_at=? WHERE run_id=?",
                (now(), run),
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
