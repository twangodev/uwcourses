"""Preserve historical timestamps and distinguish imported snapshots."""

from alembic import op

revision = "0002_observation_time"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().config.attributes["kind"] == "pipeline":
        connection = op.get_bind()
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN observed_at TEXT")
        connection.exec_driver_sql(
            "ALTER TABLE runs ADD COLUMN origin TEXT NOT NULL DEFAULT 'scrape'"
        )
        connection.exec_driver_sql("ALTER TABLE runs ADD COLUMN source_revision TEXT")
        connection.exec_driver_sql("UPDATE runs SET observed_at=started_at")
        connection.exec_driver_sql("DROP VIEW IF EXISTS current_observations")
        connection.exec_driver_sql("PRAGMA user_version=2")


def downgrade():
    raise RuntimeError("Private pipeline migrations are forward-only")
