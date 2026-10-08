"""Named Core tables for persistent snapshots, jobs, and disposable archives."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
)

pipeline = MetaData()
processing = MetaData()
archive = MetaData()

runs = Table(
    "runs",
    pipeline,
    Column("run_id", Text, primary_key=True, nullable=True),
    Column("semester", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("completed_at", Text),
    Column("status", Text, nullable=False),
    Column("config_json", Text, nullable=False),
    Column("revision", Text),
    Column("observed_at", Text),
    Column("origin", Text, nullable=False, server_default="scrape"),
    Column("source_revision", Text),
)
stages = Table(
    "stages",
    pipeline,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True, nullable=True),
    Column("stage", Text, primary_key=True, nullable=True),
    Column("status", Text, nullable=False),
    Column("error", Text),
    Column("updated_at", Text, nullable=False),
)
observations = Table(
    "observations",
    pipeline,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True, nullable=True),
    Column("source", Text, primary_key=True, nullable=False),
    Column("kind", Text, primary_key=True, nullable=False),
    Column("entity_id", Text, primary_key=True, nullable=False),
    Column("source_url", Text, nullable=False),
    Column("observed_at", Text, nullable=False),
    Column("content_hash", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    CheckConstraint("json_valid(payload_json)"),
)
Index("observation_kind", observations.c.run_id, observations.c.kind)
responses = Table(
    "responses",
    pipeline,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True, nullable=True),
    Column("source", Text, primary_key=True, nullable=True),
    Column("fingerprint", Text, primary_key=True, nullable=True),
    Column("url", Text, nullable=False),
    Column("status", Integer, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("body_hash", Text, nullable=False),
    Column("fetched_at", Text, nullable=False),
)
artifacts = Table(
    "artifacts",
    pipeline,
    Column("run_id", Text, ForeignKey("runs.run_id"), primary_key=True, nullable=True),
    Column("name", Text, primary_key=True, nullable=True),
    Column("input_hash", Text, nullable=False),
    Column("config_json", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
)
jobs = Table(
    "jobs",
    processing,
    Column("job_id", Text, primary_key=True, nullable=True),
    Column("source_run", Text, nullable=False),
    Column("spec_json", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)
results = Table(
    "results",
    processing,
    Column("job_id", Text, ForeignKey("jobs.job_id"), primary_key=True, nullable=True),
    Column("course_id", Text, primary_key=True, nullable=True),
    Column("cache_key", Text, nullable=False),
    Column("input_json", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("output_json", Text),
    Column("usage_json", Text),
    Column("error", Text),
    Column("attempts", Integer, nullable=False, server_default="0"),
)
output_cache = Table(
    "output_cache",
    processing,
    Column("cache_key", Text, primary_key=True, nullable=True),
    Column("output_json", Text, nullable=False),
    Column("usage_json", Text, nullable=False),
)


# These retain the published column order/types. Archive schema versions are
# independent of private database migrations and remain disposable per release.
def archive_table(name, columns, *, keys=(), references=(), required=(), integers=()):
    return Table(
        name,
        archive,
        *(
            Column(
                column,
                Integer if column in integers else Text,
                primary_key=column in keys,
                nullable=column not in required,
            )
            for column in columns.split()
        ),
        *(ForeignKeyConstraint(local, remote) for local, remote in references),
    )


archive_runs = archive_table(
    "runs",
    "run_id semester observed_at origin source_revision",
    keys=("run_id",),
    required=("semester", "observed_at", "origin"),
)
archive_observations = archive_table(
    "observations",
    "run_id source kind entity_id source_url observed_at content_hash payload_json",
    keys=("run_id", "source", "kind", "entity_id"),
    references=[(["run_id"], ["runs.run_id"])],
)
subjects = archive_table(
    "subjects",
    "run_id subject_id name",
    keys=("run_id", "subject_id"),
    required=("name",),
    references=[(["run_id"], ["runs.run_id"])],
)
course_versions = archive_table(
    "course_versions",
    "version_id course_number title description prerequisites_json record_json",
    keys=("version_id",),
    required=("course_number", "title", "description", "record_json"),
    integers=("course_number",),
)
course_snapshots = archive_table(
    "course_snapshots",
    "run_id course_id version_id",
    keys=("run_id", "course_id"),
    required=("version_id",),
    references=[
        (["run_id"], ["runs.run_id"]),
        (["version_id"], ["course_versions.version_id"]),
    ],
)
Index(
    "course_snapshots_course", course_snapshots.c.course_id, course_snapshots.c.run_id
)
course_subjects = archive_table(
    "course_subjects",
    "run_id course_id subject_id",
    keys=("run_id", "course_id", "subject_id"),
    references=[
        (
            ["run_id", "course_id"],
            ["course_snapshots.run_id", "course_snapshots.course_id"],
        ),
        (["run_id", "subject_id"], ["subjects.run_id", "subjects.subject_id"]),
    ],
)
terms = archive_table(
    "terms",
    "run_id term_id name",
    keys=("run_id", "term_id"),
    required=("name",),
    references=[(["run_id"], ["runs.run_id"])],
)
instructors = archive_table(
    "instructors",
    "run_id instructor_id name email official_name department position details_json",
    keys=("run_id", "instructor_id"),
    references=[(["run_id"], ["runs.run_id"])],
)
grades = archive_table(
    "grades",
    "run_id course_id term_id distribution_json",
    keys=("run_id", "course_id", "term_id"),
    required=("distribution_json",),
    references=[
        (
            ["run_id", "course_id"],
            ["course_snapshots.run_id", "course_snapshots.course_id"],
        ),
        (["run_id", "term_id"], ["terms.run_id", "terms.term_id"]),
    ],
)
offerings = archive_table(
    "offerings",
    "run_id offering_id term_id course_id source_course_id source_subject_id course_reference_json details_json",
    keys=("run_id", "offering_id"),
    references=[
        (["run_id"], ["runs.run_id"]),
        (["run_id", "term_id"], ["terms.run_id", "terms.term_id"]),
        (
            ["run_id", "course_id"],
            ["course_snapshots.run_id", "course_snapshots.course_id"],
        ),
    ],
)
sections = archive_table(
    "sections",
    "run_id offering_id section_id section_type section_number details_json",
    keys=("run_id", "offering_id", "section_id"),
    references=[
        (["run_id", "offering_id"], ["offerings.run_id", "offerings.offering_id"])
    ],
)
section_instructors = archive_table(
    "section_instructors",
    "run_id offering_id section_id instructor_name instructor_id",
    keys=("run_id", "offering_id", "section_id", "instructor_name"),
    references=[
        (
            ["run_id", "offering_id", "section_id"],
            ["sections.run_id", "sections.offering_id", "sections.section_id"],
        ),
        (
            ["run_id", "instructor_id"],
            ["instructors.run_id", "instructors.instructor_id"],
        ),
    ],
)
meetings = archive_table(
    "meetings",
    "run_id course_id meeting_id start_time end_time details_json",
    keys=("run_id", "course_id", "meeting_id"),
    references=[
        (
            ["run_id", "course_id"],
            ["course_snapshots.run_id", "course_snapshots.course_id"],
        )
    ],
    integers=("start_time", "end_time"),
)
derived_artifacts = archive_table(
    "derived_artifacts",
    "run_id name input_hash config_json payload_json",
    keys=("run_id", "name"),
    references=[(["run_id"], ["runs.run_id"])],
)
enrichment_jobs = archive_table(
    "enrichment_jobs",
    "job_id run_id task spec_json selected_courses total_courses created_at",
    keys=("job_id",),
    references=[(["run_id"], ["runs.run_id"])],
    integers=("selected_courses", "total_courses"),
)
release_enrichments = archive_table(
    "release_enrichments",
    "job_id is_selected",
    keys=("job_id",),
    required=("is_selected",),
    references=[(["job_id"], ["enrichment_jobs.job_id"])],
    integers=("is_selected",),
)
enrichment_outputs = archive_table(
    "enrichment_outputs",
    "output_id model model_revision output_json usage_json",
    keys=("output_id",),
)
course_enrichment_runs = archive_table(
    "course_enrichment_runs",
    "job_id run_id course_id output_id",
    keys=("job_id", "course_id"),
    references=[
        (["job_id"], ["enrichment_jobs.job_id"]),
        (["output_id"], ["enrichment_outputs.output_id"]),
        (
            ["run_id", "course_id"],
            ["course_snapshots.run_id", "course_snapshots.course_id"],
        ),
    ],
)
enrichment_output_sections = archive_table(
    "enrichment_output_sections",
    "output_id section status value_json candidate_json error",
    keys=("output_id", "section"),
    references=[(["output_id"], ["enrichment_outputs.output_id"])],
)
