"""Adopt old SQLite schemas and upgrade atomically without copying observations."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .schema import pipeline, processing


def upgrade_database(db, kind):
    metadata = {"pipeline": pipeline, "processing": processing}[kind]
    connection = db.connection
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).with_name("migrations"))
    )
    config.attributes.update(connection=connection, kind=kind)
    try:
        # Serialize schema initialization across commands, before inspecting/stamping.
        db.execute("BEGIN IMMEDIATE")
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if kind == "pipeline" and version not in {0, 1, 2}:
            raise ValueError("Database schema is newer than this pipeline")
        if "alembic_version" not in tables:
            existing = tables & set(metadata.tables)
            if existing:
                if existing != set(metadata.tables) or (
                    kind == "pipeline" and version == 0
                ):
                    raise ValueError(
                        f"Unrecognized {kind} database schema; refusing to baseline"
                    )
                for table in metadata.tables.values():
                    expected = set(table.c.keys())
                    if kind == "pipeline" and version == 1 and table.name == "runs":
                        expected -= {"observed_at", "origin", "source_revision"}
                    actual = {
                        column["name"] for column in inspector.get_columns(table.name)
                    }
                    if actual != expected:
                        raise ValueError(
                            f"Unrecognized columns in {table.name}; refusing to baseline"
                        )
                    primary_key = inspector.get_pk_constraint(table.name)[
                        "constrained_columns"
                    ]
                    if primary_key != [
                        column.name for column in table.primary_key.columns
                    ]:
                        raise ValueError(
                            f"Unrecognized primary key in {table.name}; refusing to baseline"
                        )
                command.stamp(
                    config,
                    "0001_baseline"
                    if kind == "pipeline" and version == 1
                    else "0002_observation_time",
                )
            elif tables or version:
                raise ValueError(
                    f"Unrecognized {kind} database schema; refusing to initialize"
                )
        command.upgrade(config, "head")
        db.commit()
    except Exception:
        db.rollback()
        raise
