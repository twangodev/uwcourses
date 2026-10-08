"""Typed relational projections from the self-contained archive."""

from collections import defaultdict
from datetime import datetime, timezone
import json
import sqlite3

import pyarrow as pa

from .models import canonical, digest

TEXT = pa.string()
INT = pa.int64()
TIME = pa.timestamp("us", tz="UTC")
STRINGS = pa.list_(TEXT)
OBS = [("run_id", TEXT), ("observed_at", TIME)]
GRADE_NAMES = "a ab b bc c d f satisfactory unsatisfactory credit no_credit passed incomplete no_work not_reported other total".split()
GRADE_KEYS = dict(
    zip(
        GRADE_NAMES,
        "aCount abCount bCount bcCount cCount dCount fCount sCount uCount crCount nCount pCount iCount nwCount nrCount otherCount total".split(),
    )
)
SCHEMAS = {
    "course_entities": pa.schema(
        [("course_uid", TEXT), ("first_observed_at", TIME), ("last_observed_at", TIME)]
    ),
    "course_aliases": pa.schema(
        OBS
        + [
            ("course_uid", TEXT),
            ("course_id", TEXT),
            ("subject", TEXT),
            ("course_number", INT),
        ]
    ),
    "course_observations": pa.schema(
        OBS
        + [
            ("semester", TEXT),
            ("course_uid", TEXT),
            ("course_id", TEXT),
            ("catalog_version_id", TEXT),
            ("record_version_id", TEXT),
        ]
    ),
    "instructors": pa.schema(
        [
            ("instructor_uid", TEXT),
            ("source", TEXT),
            ("source_instructor_id", TEXT),
            ("identity_basis", TEXT),
            ("identity_status", TEXT),
            ("name", TEXT),
            ("email", TEXT),
            ("first_observed_at", TIME),
            ("last_observed_at", TIME),
        ]
    ),
    "instructor_aliases": pa.schema(
        OBS
        + [
            ("instructor_uid", TEXT),
            ("name", TEXT),
            ("source", TEXT),
            ("legacy_instructor_id", TEXT),
        ]
    ),
    "sections_current": pa.schema(
        OBS
        + [
            ("section_uid", TEXT),
            ("term_id", TEXT),
            ("source_section_id", TEXT),
            ("identity_basis", TEXT),
            ("section_number", TEXT),
            ("section_type", TEXT),
            ("instruction_mode", TEXT),
            ("capacity", INT),
            ("enrolled", INT),
            ("waitlisted", INT),
            ("start_date", TIME),
            ("end_date", TIME),
        ]
    ),
    "offering_sections": pa.schema(
        OBS + [("offering_id", TEXT), ("course_uid", TEXT), ("section_uid", TEXT)]
    ),
    "section_instructors_current": pa.schema(
        OBS + [("section_uid", TEXT), ("instructor_uid", TEXT)]
    ),
    "meetings_current": pa.schema(
        OBS
        + [
            ("meeting_id", TEXT),
            ("course_uid", TEXT),
            ("course_id", TEXT),
            ("name", TEXT),
            ("meeting_type", TEXT),
            ("starts_at", TIME),
            ("ends_at", TIME),
            ("building", TEXT),
            ("room", TEXT),
            ("latitude", pa.float64()),
            ("longitude", pa.float64()),
            ("instructor_names", STRINGS),
        ]
    ),
    "section_grades_latest": pa.schema(
        OBS
        + [
            ("grade_section_uid", TEXT),
            ("source_course_id", TEXT),
            ("course_uid", TEXT),
            ("course_id", TEXT),
            ("course_match_status", TEXT),
            ("term_id", TEXT),
            ("section_number", INT),
        ]
        + [(name, INT) for name in GRADE_NAMES]
    ),
    "grade_section_instructors": pa.schema(
        OBS + [("grade_section_uid", TEXT), ("instructor_uid", TEXT)]
    ),
    "llm_results": pa.schema(
        OBS
        + [
            ("course_uid", TEXT),
            ("course_id", TEXT),
            ("catalog_version_id", TEXT),
            ("record_version_id", TEXT),
            ("job_id", TEXT),
            ("output_id", TEXT),
            ("section", TEXT),
            ("status", TEXT),
            ("value_json", TEXT),
            ("candidate_json", TEXT),
            ("error", TEXT),
            ("model", TEXT),
            ("model_revision", TEXT),
            ("selected_for_release", pa.bool_()),
        ]
    ),
}
DESCRIPTIONS = {
    "course_entities": "Persistent course identities. Aliases share an identity only when unambiguous; conflicting identities and renumberings are not automatically merged. Preserve public/course_identity_registry.json when moving the pipeline workspace.",
    "course_aliases": "Observed subject/number aliases for each catalog reference. Join by run_id plus subject/course_number; multiple matches remain explicit.",
    "course_observations": "Normalized observation-to-version links. semester labels the scrape context; observed_at is observation time, not a validity interval.",
    "instructors": "Latest observed instructor labels, with stable source-scoped IDs. Madgrades IDs and UW netids are not merged by name. name_only identities are unresolved labels, not verified unique people.",
    "instructor_aliases": "Names observed for source-scoped instructor identities. Legacy name-derived IDs are retained as unresolved identities.",
    "sections_current": "One row per enrollment term/class number in the selected snapshot. If a class number is unavailable, identity stays scoped to its offering and section. Join offerings through offering_sections; cross-listings do not duplicate the class.",
    "offering_sections": "Many-to-many offering/class links. A cross-listed class may belong to several catalog offerings.",
    "section_instructors_current": "Instructors explicitly reported for each enrollment class. These links do not infer equivalence with Madgrades identities.",
    "meetings_current": "Expanded meeting occurrences from the selected snapshot, with UTC timestamps. Instructor names are source labels; no identity is inferred from these names.",
    "section_grades_latest": "One latest observed Madgrades distribution per source course UUID, term, and section number. Course matches use snapshot-local aliases; unresolved matches stay null. Unnumbered legacy sections remain in archive observations. Zero and missing counts stay distinct. Do not sum course aggregates with section counts.",
    "grade_section_instructors": "Instructors reported for the corresponding latest grade section. Co-teachers share one distribution; joining this table can duplicate counts, and does not attribute individual students to a teacher.",
    "llm_results": "Version-bound section outputs including rejected candidates and status. All archived jobs are retained; selected_for_release marks explicitly selected jobs, not necessarily the newest result. Full conversations remain in llm_traces.",
}


def instant(milliseconds):
    return (
        datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat()
        if milliseconds is not None
        else None
    )


def instructor_identity(source, record, scope):
    if source == "madgrades" and record.get("id") is not None:
        key, basis = str(record["id"]), "source_id"
    elif source == "enrollment" and record.get("netid"):
        key, basis = record["netid"].strip().casefold(), "netid"
    elif source == "enrollment" and record.get("email"):
        key, basis = record["email"].strip().casefold(), "email"
    else:
        key, basis = digest([scope, record.get("name")]), "name_only"
    return {
        "instructor_uid": "instructor_" + digest([source, basis, key])[:24],
        "source": source,
        "source_instructor_id": key if basis != "name_only" else None,
        "identity_basis": basis,
        "identity_status": "unresolved"
        if basis == "name_only"
        else "source_identified",
    }


class ShapeRows:
    """Disk-backed deduplication keeps historical alias and section counts bounded."""

    def __init__(self, directory):
        self.path = directory / ".shape.sqlite"
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=OFF")
        for name in SCHEMAS:
            self.db.execute(f"CREATE TABLE {name}(key TEXT PRIMARY KEY, value TEXT)")

    def add(self, table, key, value):
        if table == "sections_current":
            previous = self.db.execute(
                "SELECT value FROM sections_current WHERE key=?", (canonical(key),)
            ).fetchone()
            if previous and previous[0] != canonical(value):
                raise ValueError(f"Conflicting enrollment class projections: {key}")
        self.db.execute(
            f"INSERT OR REPLACE INTO {table} VALUES(?,?)",
            (canonical(key), canonical(value)),
        )

    def instructor(self, source, record, scope, observation, legacy=None):
        identity = instructor_identity(source, record, scope)
        key = identity["instructor_uid"]
        previous = self.db.execute(
            "SELECT value FROM instructors WHERE key=?", (canonical(key),)
        ).fetchone()
        prior = json.loads(previous[0]) if previous else None
        first = (
            min(prior["first_observed_at"], observation["observed_at"])
            if prior
            else observation["observed_at"]
        )
        value = {
            **identity,
            "name": record.get("name"),
            "email": record.get("email"),
            "first_observed_at": first,
            "last_observed_at": observation["observed_at"],
        }
        if prior and prior["last_observed_at"] > observation["observed_at"]:
            value = {**prior, "first_observed_at": first}
        self.add("instructors", key, value)
        self.add(
            "instructor_aliases",
            [observation["run_id"], key, record.get("name"), legacy],
            {
                **observation,
                "instructor_uid": key,
                "name": record.get("name"),
                "source": source,
                "legacy_instructor_id": legacy,
            },
        )
        return key

    def export(self, directory):
        from .public_data import write_rows, timestamp

        counts = {}
        self.db.commit()
        for name, schema in SCHEMAS.items():

            def rows():
                for (raw,) in self.db.execute(f"SELECT value FROM {name} ORDER BY key"):
                    value = json.loads(raw)
                    for field in schema:
                        if (
                            pa.types.is_timestamp(field.type)
                            and value.get(field.name) is not None
                        ):
                            value[field.name] = timestamp(value[field.name])
                    yield value

            counts[name] = write_rows(
                directory / f"{name}.parquet",
                schema,
                rows(),
                max_text_bytes=16 * 1024 * 1024,
            )
        return counts

    def close(self):
        self.db.close()
        self.path.unlink(missing_ok=True)


def write_shape(db, directory, runs, source_run, identities):
    from .public_data import catalog_record

    shape = ShapeRows(directory)
    try:
        entities = {}
        aliases = defaultdict(set)
        grade_runs = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT run_id FROM observations WHERE kind='grades' AND source='madgrades'"
            )
        }
        for row in db.execute("""SELECT s.*,v.title,v.description,v.prerequisites_json,v.record_json
            FROM course_snapshots s JOIN course_versions v USING(version_id)
            ORDER BY s.course_id,s.run_id"""):
            run, label = row["run_id"], row["course_id"]
            uid = identities[label]
            observed = runs[run]["observed_at"]
            obs = {"run_id": run, "observed_at": observed}
            subject_part, number = label.rsplit(" ", 1)
            reference = {
                "subjects": subject_part.split("/"),
                "course_number": int(number),
            }
            catalog = catalog_record(label, json.loads(row["record_json"]))
            shape.add(
                "course_observations",
                [run, label],
                {
                    **obs,
                    "semester": runs[run]["semester"],
                    "course_uid": uid,
                    "course_id": label,
                    "catalog_version_id": catalog["catalog_version_id"],
                    "record_version_id": row["version_id"],
                },
            )
            for subject in reference["subjects"]:
                shape.add(
                    "course_aliases",
                    [run, label, subject],
                    {
                        **obs,
                        "course_uid": uid,
                        "course_id": label,
                        "subject": subject,
                        "course_number": int(number),
                    },
                )
                if run in grade_runs:
                    aliases[(run, f"{subject} {int(number)}")].add(label)
            bounds = entities.setdefault(uid, [observed, observed])
            bounds[0] = min(bounds[0], observed)
            bounds[1] = max(bounds[1], observed)
        for uid, (first, last) in entities.items():
            shape.add(
                "course_entities",
                uid,
                {
                    "course_uid": uid,
                    "first_observed_at": first,
                    "last_observed_at": last,
                },
            )

        # Name-derived historical records remain available as unresolved labels.
        for row in db.execute("""SELECT i.run_id,i.instructor_id,i.name,i.email FROM instructors i
            JOIN runs r USING(run_id) ORDER BY r.observed_at,i.run_id,i.instructor_id"""):
            obs = {
                "run_id": row["run_id"],
                "observed_at": runs[row["run_id"]]["observed_at"],
            }
            shape.instructor(
                "legacy",
                {"name": row["name"], "email": row["email"]},
                row["instructor_id"],
                obs,
                legacy=row["instructor_id"],
            )

        obs = {"run_id": source_run, "observed_at": runs[source_run]["observed_at"]}
        for row in db.execute(
            """SELECT s.*,o.term_id,o.course_id FROM sections s
            JOIN offerings o USING(run_id,offering_id) WHERE s.run_id=? ORDER BY s.offering_id,s.section_id""",
            (source_run,),
        ):
            detail = json.loads(row["details_json"])
            class_number = (detail.get("classUniqueId") or {}).get("classNumber")
            section_uid = (
                f"uw-section:{row['term_id']}:{class_number}"
                if class_number is not None
                else "uw-section_"
                + digest([row["term_id"], row["offering_id"], row["section_id"]])[:24]
            )
            enrollment = detail.get("enrollmentStatus") or {}
            shape.add(
                "sections_current",
                section_uid,
                {
                    **obs,
                    "section_uid": section_uid,
                    "term_id": row["term_id"],
                    "source_section_id": str(class_number)
                    if class_number is not None
                    else None,
                    "identity_basis": "class_number"
                    if class_number is not None
                    else "offering_section",
                    "section_number": row["section_number"],
                    "section_type": row["section_type"],
                    "instruction_mode": detail.get("instructionMode"),
                    "capacity": enrollment.get("capacity"),
                    "enrolled": enrollment.get("currentlyEnrolled"),
                    "waitlisted": enrollment.get("waitlistCurrentSize"),
                    "start_date": instant(detail.get("startDate")),
                    "end_date": instant(detail.get("endDate")),
                },
            )
            shape.add(
                "offering_sections",
                [row["offering_id"], section_uid],
                {
                    **obs,
                    "offering_id": row["offering_id"],
                    "section_uid": section_uid,
                    "course_uid": identities.get(row["course_id"]),
                },
            )
            for person in detail.get("instructors", []):
                name = person.get("name") or {}
                name = (
                    " ".join(
                        str(name.get(part) or "").strip() for part in ["first", "last"]
                    ).strip()
                    if isinstance(name, dict)
                    else str(name)
                )
                uid = shape.instructor(
                    "enrollment", {**person, "name": name}, [section_uid, name], obs
                )
                shape.add(
                    "section_instructors_current",
                    [section_uid, uid],
                    {**obs, "section_uid": section_uid, "instructor_uid": uid},
                )
        for row in db.execute(
            "SELECT * FROM meetings WHERE run_id=? ORDER BY course_id,meeting_id",
            (source_run,),
        ):
            detail = json.loads(row["details_json"])
            location = detail.get("location") or {}
            coordinates = location.get("coordinates") or [None, None]
            shape.add(
                "meetings_current",
                [row["course_id"], row["meeting_id"]],
                {
                    **obs,
                    "meeting_id": row["meeting_id"],
                    "course_uid": identities[row["course_id"]],
                    "course_id": row["course_id"],
                    "name": detail.get("name"),
                    "meeting_type": detail.get("type"),
                    "starts_at": instant(row["start_time"]),
                    "ends_at": instant(row["end_time"]),
                    "building": location.get("building"),
                    "room": str(location["room"])
                    if location.get("room") is not None
                    else None,
                    "latitude": coordinates[0],
                    "longitude": coordinates[1],
                    "instructor_names": detail.get("instructors") or [],
                },
            )

        seen_terms = set()
        for (
            row
        ) in db.execute("""SELECT o.* FROM observations o JOIN runs r USING(run_id)
            WHERE o.kind='grades' AND o.source='madgrades'
            ORDER BY r.observed_at DESC,o.run_id DESC,o.entity_id"""):
            data = json.loads(row["payload_json"])
            source_id = str(
                data.get("source_id") or data.get("courseUuid") or row["entity_id"]
            )
            reference = data.get("course_reference") or {}
            label = f"{'/'.join(sorted(reference.get('subjects', [])))} {reference.get('course_number')}"
            matches = set()
            for subject in reference.get("subjects", []):
                matches.update(
                    aliases.get(
                        (row["run_id"], f"{subject} {reference['course_number']}"),
                        set(),
                    )
                )
            if label in matches:
                matched = label
            else:
                matched = next(iter(matches)) if len(matches) == 1 else None
            obs = {
                "run_id": row["run_id"],
                "observed_at": runs[row["run_id"]]["observed_at"],
            }
            for offering in data.get("courseOfferings", []):
                term = str(offering["termCode"])
                term_key = (source_id, term)
                latest = term_key not in seen_terms
                seen_terms.add(term_key)
                for section in offering.get("sections", []):
                    number = section.get("sectionNumber")
                    if number is None:
                        # Unkeyed legacy sections remain in raw observations.
                        continue
                    uid = (
                        "madgrades-section_"
                        + digest([source_id, term, int(number)])[:24]
                    )
                    people = [
                        shape.instructor(
                            "madgrades", person, [uid, person.get("name")], obs
                        )
                        for person in section.get("instructors", [])
                    ]
                    if not latest:
                        continue
                    shape.add(
                        "section_grades_latest",
                        uid,
                        {
                            **obs,
                            "grade_section_uid": uid,
                            "source_course_id": source_id,
                            "course_uid": identities.get(matched),
                            "course_id": matched,
                            "course_match_status": "matched"
                            if matched
                            else "ambiguous"
                            if matches
                            else "unmatched",
                            "term_id": term,
                            "section_number": int(number),
                            **{
                                name: section.get(key)
                                for name, key in GRADE_KEYS.items()
                            },
                        },
                    )
                    for person in people:
                        shape.add(
                            "grade_section_instructors",
                            [uid, person],
                            {**obs, "grade_section_uid": uid, "instructor_uid": person},
                        )

        for row in db.execute("""SELECT b.*,s.section,s.status,s.value_json,s.candidate_json,s.error,o.model,o.model_revision,r.is_selected
            FROM course_enrichment_runs b JOIN enrichment_outputs o USING(output_id)
            JOIN enrichment_output_sections s USING(output_id) JOIN release_enrichments r USING(job_id)
            ORDER BY b.job_id,b.course_id,s.section"""):
            version = shape.db.execute(
                "SELECT value FROM course_observations WHERE key=?",
                (canonical([row["run_id"], row["course_id"]]),),
            ).fetchone()
            if version is None:
                raise ValueError("LLM output has no course observation")
            version = json.loads(version[0])
            shape.add(
                "llm_results",
                [row["job_id"], row["course_id"], row["section"]],
                {
                    **{
                        key: version[key]
                        for key in [
                            "run_id",
                            "observed_at",
                            "course_uid",
                            "course_id",
                            "catalog_version_id",
                            "record_version_id",
                        ]
                    },
                    **{
                        key: row[key]
                        for key in [
                            "job_id",
                            "output_id",
                            "section",
                            "status",
                            "value_json",
                            "candidate_json",
                            "error",
                            "model",
                            "model_revision",
                        ]
                    },
                    "selected_for_release": bool(row["is_selected"]),
                },
            )
        return shape.export(directory)
    finally:
        shape.close()
