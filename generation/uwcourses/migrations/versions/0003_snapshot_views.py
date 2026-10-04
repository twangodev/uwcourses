"""Version view definitions and prevent auxiliary runs advancing course views."""

from alembic import op

revision = "0003_snapshot_views"
down_revision = "0002_observation_time"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().config.attributes["kind"] != "pipeline":
        return
    connection = op.get_bind()
    latest = """SELECT r.run_id FROM runs r WHERE r.status='complete'
        AND EXISTS(SELECT 1 FROM observations o WHERE o.run_id=r.run_id AND o.kind='courses')
        ORDER BY r.observed_at DESC,(r.origin='scrape') DESC,r.run_id DESC LIMIT 1"""
    projections = {
        "courses": "entity_id AS course_id, json_extract(payload_json,'$.course_reference.course_number') AS course_number, json_extract(payload_json,'$.course_title') AS title, json_extract(payload_json,'$.description') AS description, json_extract(payload_json,'$.prerequisites') AS prerequisites_json",
        "subjects": "entity_id AS subject_id, json_extract(payload_json,'$.name') AS name",
        "terms": "entity_id AS term_id, json_extract(payload_json,'$.name') AS name",
        "instructors": "entity_id AS instructor_id, json_extract(payload_json,'$.name') AS name, json_extract(payload_json,'$.email') AS email",
        "offerings": "entity_id AS offering_id, json_extract(payload_json,'$.term') AS term_id, json_extract(payload_json,'$.course_reference') AS course_reference_json, json_extract(payload_json,'$.sections') AS sections_json",
        "grades": "entity_id AS source_course_id, json_extract(payload_json,'$.course_reference') AS course_reference_json, json_extract(payload_json,'$.cumulative') AS cumulative_json, json_extract(payload_json,'$.courseOfferings') AS terms_json",
    }
    connection.exec_driver_sql("DROP VIEW IF EXISTS current_observations")
    connection.exec_driver_sql(
        f"CREATE VIEW current_observations AS SELECT * FROM observations WHERE run_id=({latest})"
    )
    for kind, projection in projections.items():
        connection.exec_driver_sql(f"DROP VIEW IF EXISTS current_{kind}")
        connection.exec_driver_sql(f"DROP VIEW IF EXISTS {kind}")
        connection.exec_driver_sql(
            f"CREATE VIEW {kind} AS SELECT run_id,source,source_url,observed_at,{projection} FROM observations WHERE kind='{kind}'"
        )
        connection.exec_driver_sql(
            f"CREATE VIEW current_{kind} AS SELECT * FROM {kind} WHERE run_id=({latest})"
        )
    connection.exec_driver_sql("DROP VIEW IF EXISTS course_subjects")
    connection.exec_driver_sql(
        "CREATE VIEW course_subjects AS SELECT o.run_id,o.entity_id AS course_id,j.value AS subject_id FROM observations o,json_each(o.payload_json,'$.course_reference.subjects') j WHERE o.kind='courses'"
    )


def downgrade():
    raise RuntimeError("Private pipeline migrations are forward-only")
