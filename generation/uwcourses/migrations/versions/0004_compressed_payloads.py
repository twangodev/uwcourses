"""Compress private payloads while preserving logical values and public archives."""

from alembic import op
from sqlalchemy import MetaData, func, insert, select, update

from uwcourses.schema import observations, pipeline, processing, runs
from uwcourses.storage_codec import CompressedText

revision = "0004_compressed_payloads"
down_revision = "0003_snapshot_views"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    kind = op.get_context().config.attributes["kind"]
    metadata = pipeline if kind == "pipeline" else processing
    if kind == "pipeline":
        views = connection.exec_driver_sql(
            "SELECT name,sql FROM sqlite_master WHERE type='view' ORDER BY name"
        ).fetchall()
        quote = connection.dialect.identifier_preparer.quote_identifier
        for name, _ in views:
            connection.exec_driver_sql(f"DROP VIEW {quote(name)}")
        replacement_metadata = MetaData()
        runs.to_metadata(replacement_metadata)
        replacement = observations.to_metadata(
            replacement_metadata, name="_uwcourses_observations"
        )
        replacement.indexes.clear()
        replacement.create(connection)
        connection.execute(
            insert(replacement).from_select(
                list(observations.c.keys()),
                select(
                    *(
                        func.uwcourses_pack(column)
                        if column.name == "payload_json"
                        else column
                        for column in observations.c
                    )
                ),
            )
        )
        observations.drop(connection)
        connection.exec_driver_sql(
            "ALTER TABLE _uwcourses_observations RENAME TO observations"
        )
        for index in observations.indexes:
            index.create(connection)
        for _, sql in views:
            connection.exec_driver_sql(
                sql.replace(
                    "json_extract(payload_json,",
                    "json_extract(uwcourses_text(payload_json),",
                ).replace(
                    "json_each(o.payload_json,",
                    "json_each(uwcourses_text(o.payload_json),",
                )
            )
    for table in metadata.tables.values():
        if table.name == "observations":
            continue
        values = {
            column.name: func.uwcourses_pack(column)
            for column in table.c
            if isinstance(column.type, CompressedText)
        }
        if values:
            connection.execute(update(table).values(**values))


def downgrade():
    raise RuntimeError("Private pipeline migrations are forward-only")
