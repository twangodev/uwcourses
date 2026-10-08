"""Compile one verified HF release into disposable website assets and SQLite/D1 data."""

from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import pyarrow.parquet as pq
from .instructor_stats import attach_ratings
from .discovery import build_discovery
from .search_projection import (
    build_search_projection,
    TABLES as SEARCH_TABLES,
    POLICY_PATH,
)
from .campus import CampusSchedule

ROOT = Path.cwd()
REPO = "twangodev/uwcourses"
IMPORTER_VERSION = "10"
GRADES = ["a", "ab", "b", "bc", "c", "d", "f"]
WEIGHTS = [4, 3.5, 3, 2.5, 2, 1, 0]
MAX_CHUNK = 1024 * 1024


def encode(value):
    return json.dumps(
        value, default=str, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode(value))


def normalize(value):
    value = re.sub(r"[^A-Z0-9]", "", value.upper())
    return re.sub(r"^CS(?=\d)", "COMPSCI", value)


def building_footprints(records):
    """Project official geometry onto the existing campus basemap, retaining holes."""
    footprints = []
    for record in records:
        geometry = json.loads(record["geometry_json"] or "null")
        if not geometry or geometry["type"] not in {"Polygon", "MultiPolygon"}:
            continue
        polygons = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        projected = [
            [
                [
                    [
                        round((lng + 89.425) / 0.034 * 900, 2),
                        round((43.082 - lat) / 0.014 * 505, 2),
                    ]
                    for lng, lat in ring
                ]
                for ring in polygon
            ]
            for polygon in polygons
        ]
        meta = json.loads(record["meta_json"] or "{}")
        footprints.append(
            {
                "id": record["building_uid"],
                "name": record["name"],
                "names": sorted(
                    {
                        record["name"],
                        *(
                            value
                            for key in ("cname", "lname")
                            if isinstance(value := meta.get(key), str) and value
                        ),
                    }
                ),
                "buildingNumber": record["building_number"],
                "sourceUrl": record["source_url"],
                "points": projected[0][0],
                "polygons": projected,
            }
        )
    return {"source": "https://map.wisc.edu/buildings/", "buildings": footprints}


def rows(source, name):
    for batch in pq.ParquetFile(source / "public" / f"{name}.parquet").iter_batches(
        batch_size=4096
    ):
        yield from batch.to_pylist()


def verify(source):
    schema = json.loads((source / "public/schema.json").read_text())
    expected = json.loads((Path(__file__).with_name("schema-v6.json")).read_text())
    if schema["version"] != expected["version"]:
        raise ValueError(f"Unsupported public schema: {schema['version']}")
    manifest = json.loads((source / "manifest.json").read_text())
    for name, table in expected["tables"].items():
        # Additive v6 table: earlier releases have no official building source.
        if name == "buildings_current" and name not in schema["tables"]:
            if (source / "public" / f"{name}.parquet").exists():
                raise ValueError("Undeclared buildings table")
            continue
        rel = f"public/{name}.parquet"
        path = source / rel
        actual = pq.ParquetFile(path)
        columns = dict(table["columns"])
        columns.update(
            {
                key: typ
                for key, typ in table.get("optional_columns", {}).items()
                if key in actual.schema_arrow.names
            }
        )
        for col, typ in columns.items():
            if (
                str(actual.schema_arrow.field(col).type).replace("element:", "item:")
                != typ
            ):
                raise ValueError(f"Incompatible {name}.{col}")
        if actual.metadata.num_rows != schema["tables"][name]["rows"]:
            raise ValueError(f"Row count mismatch: {name}")
        declared = manifest["files"][rel]
        with path.open("rb") as file:
            checksum = hashlib.file_digest(file, "sha256").hexdigest()
        if path.stat().st_size != declared["bytes"] or checksum != declared["sha256"]:
            raise ValueError(f"Checksum mismatch: {rel}")
    return manifest


def clear_learning_search(course):
    """A rejected source-bound claim invalidates its entire selected search profile."""
    course["llm_search_status"] = "stale_evidence"
    course["llm_summary"] = None
    for field in (
        "llm_topics",
        "llm_skills",
        "llm_assumed_background",
        "llm_search_phrases",
        "llm_activity_tags",
        "skills_taught",
        "activity_tags",
    ):
        course[field] = []
    for field in ("llm_skills_evidence_json", "llm_activity_tags_json"):
        if field in course:
            course[field] = "[]"


ACTIVITY_LABELS = {
    "programming",
    "data-analysis",
    "mathematical-reasoning",
    "writing",
    "lab-work",
    "presentations",
}


def grounded_learning_claims(claims, course, *, activities=False):
    """Only release claims whose citations still identify current official text."""
    outcomes = course.get("official_learning_outcomes") or []
    result = []
    if not isinstance(claims, list):
        return result
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        label = (
            claim.get("label", claim.get("text")) if activities else claim.get("text")
        )
        evidence = claim.get("evidence")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not isinstance(evidence, list)
            or not evidence
        ):
            continue
        if activities and label not in ACTIVITY_LABELS:
            continue
        citations = []
        for citation in evidence:
            if not isinstance(citation, dict) or citation.get(
                "course_id"
            ) != course.get("course_id"):
                break
            quote = citation.get("quote")
            if not isinstance(quote, str) or not quote.strip():
                break
            field = citation.get("field")
            if field == "official_learning_outcomes":
                index = citation.get("outcome_index")
                if (
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or not 0 <= index < len(outcomes)
                ):
                    break
                source = outcomes[index]
                if (
                    not source.get("source_url")
                    or citation.get("source_url") != source["source_url"]
                    or quote not in source["text"]
                ):
                    break
                citations.append(
                    {
                        **citation,
                        **{
                            key: source.get(key)
                            for key in (
                                "source",
                                "source_url",
                                "observed_at",
                                "term",
                                "catalog_year",
                            )
                        },
                    }
                )
            elif field == "description":
                if (
                    "outcome_index" in citation
                    or not course.get("source_url")
                    or citation.get("source_url") != course["source_url"]
                    or quote not in (course.get("description") or "")
                ):
                    break
                citations.append(dict(citation))
            else:
                break
        else:
            result.append({**claim, "text": label, "evidence": citations})
    return result


def course_learning_fields(course):
    """Read additive enrichment fields, retaining compatibility with older v6 releases."""
    has_cited_skills = course.get("llm_skills_evidence_json") is not None
    for target, source in (
        ("official_learning_outcomes", "official_learning_outcomes_json"),
        ("skills_taught", "llm_skills_evidence_json"),
        ("activity_tags", "llm_activity_tags_json"),
    ):
        values = json.loads(course.pop(source, None) or "[]")
        if not isinstance(values, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("text"), str)
            for item in values
        ):
            raise ValueError(f"Invalid course learning field: {source}")
        if target == "official_learning_outcomes":
            for item in values:
                if any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("text", "source", "source_url")
                ) or any(
                    item.get(key) is not None and not isinstance(item[key], str)
                    for key in ("observed_at", "term", "catalog_year")
                ):
                    raise ValueError(
                        f"Invalid course learning field: {source}; missing source identity or invalid context"
                    )
        course[target] = values
    if course.get("llm_search_status") != "valid":
        course["skills_taught"], course["activity_tags"] = [], []
    candidates = len(course["skills_taught"]) + len(course["activity_tags"])
    course["skills_taught"] = grounded_learning_claims(course["skills_taught"], course)
    course["activity_tags"] = grounded_learning_claims(
        course["activity_tags"], course, activities=True
    )
    if len(course["skills_taught"]) + len(course["activity_tags"]) != candidates:
        clear_learning_search(course)
    if has_cited_skills:
        course["llm_skills"] = [claim["text"] for claim in course["skills_taught"]]
    return course


def chunks(base, revision, kind, uid, records):
    """Bound downloads by encoded size; large individual traces are split as text."""
    urls, part, size = [], [], 2

    def flush():
        nonlocal part, size
        if not part:
            return
        rel = f"data/{revision}/{kind}/{uid}-{len(urls)}.json"
        write(base / rel, part)
        urls.append("/" + rel)
        part, size = [], 2

    for row in records:
        encoded = encode(row)
        length = len(encoded.encode())
        if length > MAX_CHUNK:
            flush()
            # Preserve full content without exceeding a single downloadable asset.
            for offset in range(0, len(encoded), 120000):
                part = [
                    {
                        "record_fragment": encoded[offset : offset + 120000],
                        "offset": offset,
                        "record_length": len(encoded),
                    }
                ]
                flush()
        else:
            if size + length + 1 > MAX_CHUNK:
                flush()
            part.append(row)
            size += length + 1
    flush()
    return urls


def grade_stats(records):
    counts = [sum((r.get(k) or 0) for r in records) for k in GRADES]
    n = sum(counts)
    return {
        "gpa": round(sum(a * b for a, b in zip(counts, WEIGHTS)) / n, 3) if n else None,
        "graded": n,
        "counts": counts,
    }


class SqlParts:
    """Keep Wrangler input files bounded without splitting SQL statements."""

    def __init__(self, directory, max_bytes=16 * 1024 * 1024):
        self.directory = directory
        self.max_bytes = max_bytes
        self.part = 0
        self.size = 0
        self.stream = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        return self

    def write(self, statement):
        size = len(statement.encode())
        if size > self.max_bytes:
            raise ValueError("SQL statement exceeds file budget")
        if self.stream is None or self.size + size > self.max_bytes:
            if self.stream:
                self.stream.close()
            self.stream = (self.directory / f"{self.part:04d}.sql").open("w")
            self.part += 1
            self.size = 0
        self.stream.write(statement)
        self.size += size

    def __exit__(self, *_):
        if self.stream:
            self.stream.close()


def compile_release(source, revision, output, static, limit=0, manifest=None):
    manifest = manifest or verify(source)
    output.mkdir(parents=True, exist_ok=True)
    dbpath = output / "site.sqlite"
    dbpath.unlink(missing_ok=True)
    db = sqlite3.connect(dbpath)
    db.executescript("""
    CREATE TABLE courses(uid TEXT PRIMARY KEY,code TEXT,title TEXT,description TEXT,credits_min REAL,credits_max REAL,gpa REAL,payload TEXT NOT NULL);
    CREATE TABLE aliases(alias TEXT,uid TEXT,PRIMARY KEY(alias,uid));
    CREATE TABLE subjects(subject TEXT,uid TEXT,PRIMARY KEY(subject,uid));
    CREATE TABLE instructors(uid TEXT PRIMARY KEY,name TEXT,current INTEGER,payload TEXT);
    CREATE TABLE teaching(instructor_uid TEXT,course_uid TEXT,term TEXT,PRIMARY KEY(instructor_uid,course_uid,term));
    CREATE TABLE grades(uid TEXT,term TEXT,section TEXT,instructors TEXT,payload TEXT,PRIMARY KEY(uid,term,section));
    CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
    CREATE VIRTUAL TABLE search USING fts5(uid UNINDEXED,kind UNINDEXED,code,title,body,tokenize='unicode61 remove_diacritics 2');
    CREATE INDEX teaching_course ON teaching(course_uid,term,instructor_uid);
    CREATE INDEX grades_course ON grades(uid,term);
    CREATE INDEX subjects_course ON subjects(uid);
    """)
    variants = defaultdict(list)
    for r in rows(source, "courses_current"):
        variants[r["course_uid"]].append(r)
    courses = {uid: dict(rs[0]) for uid, rs in variants.items()}
    for uid, c in courses.items():
        c["catalog_variants"] = variants[uid] if len(variants[uid]) > 1 else []
        c["subjects"] = sorted(
            {subject for r in variants[uid] for subject in r["subjects"]}
        )
    if limit:
        pilot = [
            r
            for r in courses.values()
            if r["course_number"] in (300, 400, 759) and "COMPSCI" in r["subjects"]
        ]
        selected = {r["course_uid"]: r for r in pilot}
        selected.update(list(courses.items())[:limit])
        courses = selected
    if not courses:
        raise ValueError("Empty course release")
    print(f"Importing {len(courses)} courses", flush=True)
    inst = {r["instructor_uid"]: r for r in rows(source, "instructors")}
    attach_ratings(inst, rows(source, "rmp_reviews"))
    section_inst = defaultdict(set)
    for r in rows(source, "section_instructors_current"):
        section_inst[r["section_uid"]].add(r["instructor_uid"])
    course_inst, inst_courses, offerings, sections = (
        defaultdict(set),
        defaultdict(set),
        defaultdict(list),
        defaultdict(list),
    )
    section_data = {r["section_uid"]: r for r in rows(source, "sections_current")}
    for r in rows(source, "offering_sections"):
        uid = r["course_uid"]
        if uid in courses:
            section = section_data[r["section_uid"]]
            sections[uid].append(section)
            for iid in section_inst[r["section_uid"]]:
                if iid not in inst:
                    raise ValueError(f"Missing instructor {iid}")
                course_inst[uid].add(iid)
                inst_courses[iid].add(uid)
                db.execute(
                    "INSERT OR IGNORE INTO teaching VALUES(?,?,?)",
                    (iid, uid, section["term_id"]),
                )
    for r in rows(source, "offerings_current"):
        if r["course_uid"] in courses:
            offerings[r["course_uid"]].append(r)
    aggregates = defaultdict(list)
    grade_conflicts = defaultdict(list)
    grade_groups = defaultdict(list)
    for r in rows(source, "grades_latest"):
        if r["course_uid"] in courses:
            grade_groups[r["course_uid"], r["term_id"]].append(r)
    for (uid, term), rs in grade_groups.items():
        counts = {
            tuple((key, val) for key, val in r.items() if isinstance(val, int))
            for r in rs
        }
        if len(counts) > 1:
            grade_conflicts[uid].extend(rs)
            continue
        r = dict(rs[0])
        r["source_aliases"] = sorted({source["course_id"] for source in rs})
        r["instructors"] = sorted(
            {name for source in rs for name in source["instructors"] if name}
        )
        aggregates[uid].append(r)
        db.execute(
            "INSERT INTO grades VALUES(?,?,?,?,?)",
            (uid, term, "", encode(r["instructors"]), encode(r)),
        )
    del grade_groups
    grade_instructors = defaultdict(set)
    for r in rows(source, "grade_section_instructors"):
        grade_instructors[r["grade_section_uid"]].add(r["instructor_uid"])
    instructor_grades = defaultdict(lambda: [0] * len(GRADES))
    instructor_sections = defaultdict(int)
    for r in rows(source, "section_grades_latest"):
        uid = r["course_uid"]
        if uid in courses:
            ids = sorted(grade_instructors[r["grade_section_uid"]])
            r["instructor_uids"] = ids
            db.execute(
                "INSERT INTO grades VALUES(?,?,?,?,?)",
                (uid, r["term_id"], r["grade_section_uid"], encode(ids), encode(r)),
            )
            for iid in ids:
                if iid in inst:
                    for index, key in enumerate(GRADES):
                        instructor_grades[iid][index] += r.get(key) or 0
                    instructor_sections[iid] += 1
                db.execute(
                    "INSERT OR IGNORE INTO teaching VALUES(?,?,?)",
                    (iid, uid, r["term_id"]),
                )
    for iid, counts in instructor_grades.items():
        inst[iid]["grade_statistics"] = {
            **grade_stats([dict(zip(GRADES, counts))]),
            "sections": instructor_sections[iid],
        }
    campus = CampusSchedule(sections)
    paths = defaultdict(dict)
    for table, kind in [
        ("courses_history", "history"),
        ("llm_traces", "traces"),
        ("rmp_reviews", "reviews"),
        ("meetings_current", "meetings"),
        ("llm_results", "results"),
    ]:
        grouped = defaultdict(list)
        for r in rows(source, table):
            if r["course_uid"] in courses:
                grouped[r["course_uid"]].append(r)
                if kind == "meetings":
                    campus.add(r)
        for uid, records in grouped.items():
            paths[uid][kind] = chunks(static, revision, kind, uid, records)
        print(f"Packed {table}", flush=True)
        del grouped
    write(output / "campus.json", campus.write(static, revision))
    write(
        output / "buildings.json",
        building_footprints(
            rows(source, "buildings_current")
            if (source / "public/buildings_current.parquet").exists()
            else []
        ),
    )
    departments = defaultdict(list)
    summaries = []
    for uid, c in courses.items():
        course_learning_fields(c)
        c["student_summary"] = json.loads(c["llm_student_summary_json"] or "{}")
        c["requirements"] = json.loads(c["llm_requirements_ast_json"] or "{}")
        if not c["requirements"].get("nodes"):
            c["requirements"] = {
                "root": "fallback",
                "status": "needs_review",
                "nodes": [
                    {
                        "id": "fallback",
                        "kind": "condition",
                        "condition": c["requirements_text"]
                        or "No prerequisites listed.",
                        "children": [],
                    }
                ],
            }
        c["instructors"] = [
            inst[i] for i in sorted(course_inst[uid], key=lambda i: inst[i]["name"])
        ]
        c["offerings"], c["sections"] = (
            offerings[uid],
            list({r["section_uid"]: r for r in sections[uid]}.values()),
        )
        c["grade_instructors"] = [
            inst[r[0]]
            for r in db.execute(
                "SELECT DISTINCT instructor_uid FROM teaching WHERE course_uid=?",
                (uid,),
            )
            if r[0] in inst
        ]
        c["grades"] = sorted(aggregates[uid], key=lambda r: r["term_id"])
        c["statistics"] = grade_stats(c["grades"])
        c["grade_conflicts"] = grade_conflicts[uid]
        c["evidence"] = paths[uid]
        c["revision"] = revision
        for key in (
            "llm_student_summary_json",
            "llm_requirements_ast_json",
            "llm_experience_json",
        ):
            c.pop(key, None)
        db.execute(
            "INSERT INTO courses VALUES(?,?,?,?,?,?,?,?)",
            (
                uid,
                c["course_id"],
                c["title"],
                c["description"],
                c["credits_min"],
                c["credits_max"],
                c["statistics"]["gpa"],
                encode(c),
            ),
        )
        search_text = (
            (c["description"] or "")
            + " "
            + " ".join(outcome["text"] for outcome in c["official_learning_outcomes"])
        )
        if c["llm_search_status"] == "valid":
            search_text += " " + " ".join(
                c["llm_topics"]
                + c["llm_skills"]
                + c["llm_search_phrases"]
                + [item["text"].replace("-", " ") for item in c["activity_tags"]]
            )
        db.execute(
            "INSERT INTO search VALUES(?,?,?,?,?)",
            (uid, "course", c["course_id"], c["title"], search_text),
        )
        item = {
            k: c[k]
            for k in ["course_uid", "course_id", "title", "credits_min", "credits_max"]
        }
        item["gpa"] = c["statistics"]["gpa"]
        summaries.append(item)
        for subject in c["subjects"]:
            departments[subject].append(item)
            db.execute("INSERT OR IGNORE INTO subjects VALUES(?,?)", (subject, uid))
            db.execute(
                "INSERT OR IGNORE INTO aliases VALUES(?,?)",
                (normalize(subject + str(c["course_number"])), uid),
            )
        db.execute(
            "INSERT OR IGNORE INTO aliases VALUES(?,?)",
            (normalize(c["course_id"]), uid),
        )
        write(output / "courses" / f"{uid}.json", c)
    # Historical aliases stay explicit: conflicts are returned as multiple search matches.
    for r in rows(source, "course_aliases"):
        if r["course_uid"] in courses:
            db.execute(
                "INSERT OR IGNORE INTO aliases VALUES(?,?)",
                (normalize(r["subject"] + str(r["course_number"])), r["course_uid"]),
            )
    summary_by_id = {c["course_uid"]: c for c in summaries}
    for iid, i in inst.items():
        i["current"] = bool(inst_courses.get(iid))
        i["courses"] = [summary_by_id[uid] for uid in sorted(inst_courses.get(iid, []))]
        i["revision"] = revision
        db.execute(
            "INSERT INTO instructors VALUES(?,?,?,?)",
            (iid, i["name"], int(i["current"]), encode(i)),
        )
        db.execute(
            "INSERT INTO search VALUES(?,?,?,?,?)",
            (iid, "instructor", "", i["name"], ""),
        )
        if i["current"]:
            write(output / "instructors" / f"{iid}.json", i)
    for subject, items in departments.items():
        write(
            output / "subjects" / f"{subject}.json",
            {
                "subject": subject,
                "courses": sorted(items, key=lambda c: c["course_id"]),
            },
        )
    build_discovery(db, rows(source, "rmp_reviews"), rows(source, "meetings_current"))
    search_projection = build_search_projection(db)
    status = {
        "search_projection": search_projection,
        "revision": revision,
        "repository": REPO,
        "schema_version": 6,
        "importer_version": IMPORTER_VERSION,
        "projection_id": hashlib.sha256(
            revision.encode()
            + Path(__file__).read_bytes()
            + Path(__file__).with_name("schema-v6.json").read_bytes()
            + Path(__file__).with_name("discovery.py").read_bytes()
            + Path(__file__).with_name("campus.py").read_bytes()
            + Path(__file__).with_name("search_projection.py").read_bytes()
            + POLICY_PATH.read_bytes()
        ).hexdigest(),
        "observed_at": manifest["observed_at"],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "courses": len(courses),
        "current_instructors": len(inst_courses),
        "limited": bool(limit),
        "terms": [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT term FROM grades UNION SELECT term FROM teaching ORDER BY term DESC"
            )
        ],
        "term": next(iter(courses.values()))["semester"],
        "departments": [
            {"subject": s, "count": len(v)} for s, v in sorted(departments.items())
        ],
        "designations": [
            {"family": family, "value": value, "label": label}
            for family, value, label in db.execute(
                "SELECT family, value, MIN(label) FROM course_designations GROUP BY family, value ORDER BY family, label"
            )
        ],
    }
    write(output / "status.json", status)
    write(
        output / "entries.json",
        {
            "courses": list(courses),
            "instructors": sorted(inst_courses),
            "subjects": sorted(departments),
        },
    )
    db.execute("INSERT INTO metadata VALUES(?,?)", ("status", encode(status)))
    db.commit()

    # Emit portable D1 SQL; keep every statement below its 100 KB query limit.
    def quote(v):
        if v is None:
            return "NULL"
        if isinstance(v, (int, float)):
            return str(v)
        return "'" + str(v).replace("'", "''") + "'"

    with SqlParts(output / "sql") as f:
        f.write("DROP TABLE IF EXISTS search;\n")
        for table in [
            "courses",
            "aliases",
            "subjects",
            "instructors",
            "teaching",
            "grades",
            "metadata",
            "course_numbers",
            "offerings",
            "grade_summaries",
            "reviews",
            "section_modes",
            "class_meetings",
            "course_seasons",
            "requisite_kinds",
            "course_designations",
            *SEARCH_TABLES,
        ]:
            f.write(f"DROP TABLE IF EXISTS {table};\n")
        for (sql,) in db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'search%' AND name NOT LIKE 'sqlite_%'"
        ):
            f.write(sql + ";\n")
        for (table,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'search%' AND name NOT LIKE 'sqlite_%'"
        ):
            cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
            for row in db.execute(f"SELECT * FROM {table}"):
                values = list(row)
                payload_index = cols.index("payload") if "payload" in cols else None
                payload = values[payload_index] if payload_index is not None else None
                split = payload is not None and len(payload.encode()) > 40000
                if payload and len(payload.encode()) > 1800000:
                    raise ValueError(
                        f"D1 row too large in {table}; move evidence to static assets"
                    )
                if split:
                    values[payload_index] = ""
                line = (
                    f"INSERT INTO {table} VALUES("
                    + ",".join(quote(v) for v in values)
                    + ");\n"
                )
                if len(line.encode()) > 90000:
                    raise ValueError(f"D1 statement too large: {table}")
                f.write(line)
                if split:
                    for offset in range(0, len(payload), 8000):
                        f.write(
                            f"UPDATE {table} SET payload=payload||"
                            + quote(payload[offset : offset + 8000])
                            + f" WHERE {cols[0]}="
                            + quote(row[0])
                            + ";\n"
                        )
        f.write(
            "CREATE VIRTUAL TABLE search USING fts5(uid UNINDEXED,kind UNINDEXED,code,title,body,tokenize='unicode61 remove_diacritics 2');\n"
        )
        for row in db.execute("SELECT uid,kind,code,title,body FROM search"):
            f.write(
                "INSERT INTO search VALUES(" + ",".join(quote(v) for v in row) + ");\n"
            )
        for (sql,) in db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND name NOT LIKE 'search%'"
        ):
            f.write(sql + ";\n")
        f.write("PRAGMA optimize;\n")
        f.write("INSERT INTO metadata VALUES('ready','true');\n")
    db.close()
    print(encode(status), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--output", type=Path, default=ROOT / ".site/import")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Development subset; never deploy a limited import",
    )
    args = parser.parse_args()
    if args.source:
        source = args.source
        revision = (
            args.revision
            or "local-"
            + hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest()[:20]
        )
    else:
        from huggingface_hub import HfApi, snapshot_download

        revision = HfApi().dataset_info(REPO, revision=args.revision or "main").sha
        source = Path(
            snapshot_download(
                REPO,
                repo_type="dataset",
                revision=revision,
                allow_patterns=[
                    "manifest.json",
                    "public/*.parquet",
                    "public/schema.json",
                ],
            )
        )
    if not re.fullmatch(r"[a-zA-Z0-9-]{8,80}", revision):
        raise ValueError("Invalid revision")
    manifest = verify(source)
    # Only this stage's directory is owned by the importer.
    if args.output.exists():
        shutil.rmtree(args.output)
    compile_release(
        source, revision, args.output, args.output / "assets", args.limit, manifest
    )


if __name__ == "__main__":
    main()
