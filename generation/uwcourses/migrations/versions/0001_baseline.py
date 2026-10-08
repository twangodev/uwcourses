"""Original private schemas; baseline existing databases without rewriting data."""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

PIPELINE = """
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
"""
PROCESSING = """
CREATE TABLE jobs(job_id TEXT PRIMARY KEY, source_run TEXT NOT NULL, spec_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE results(job_id TEXT REFERENCES jobs, course_id TEXT, cache_key TEXT NOT NULL, input_json TEXT NOT NULL, status TEXT NOT NULL, output_json TEXT, usage_json TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(job_id,course_id));
CREATE TABLE output_cache(cache_key TEXT PRIMARY KEY, output_json TEXT NOT NULL, usage_json TEXT NOT NULL);
"""


def upgrade():
    connection = op.get_bind()
    kind = op.get_context().config.attributes["kind"]
    for statement in (PIPELINE if kind == "pipeline" else PROCESSING).split(";"):
        if statement.strip():
            connection.exec_driver_sql(statement)
    if kind == "pipeline":
        connection.exec_driver_sql("PRAGMA user_version=1")


def downgrade():
    raise RuntimeError("Private pipeline migrations are forward-only")
