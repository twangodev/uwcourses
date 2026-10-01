"""Disposable website indexes for course discovery and original student reviews."""

from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo

GRADE_KEYS = ["a", "ab", "b", "bc", "c", "d", "f"]
CHICAGO = ZoneInfo("America/Chicago")
MEETING_NAME = re.compile(r"^(\S+) (.+) #(\d+)$")
INSTRUCTION_MODES = {
    "classroom instruction": "in_person",
    "online only": "online",
    "online (some classroom)": "mixed",
}
FAMILY_SLUGS = {
    "breadth": "breadth",
    "level": "catalog-level",
    "l&s credit": "liberal-arts",
    "ethnic st": "ethnic-studies",
    "ethnic studies": "ethnic-studies",
    "core gened": "core-gened",
    "honors": "honors",
    "workplace": "workplace",
    "grad 50%": "graduate-credit",
    "language": "language",
}
PLACEHOLDER_CONDITIONS = {"", "none", "no prerequisites listed", "no requisites"}
QR_VALUE = re.compile(r"quantitative reasoning ([ab])\Z")
COMMUNICATION_VALUE = re.compile(r"communication ([ab])\Z")


def build_discovery(db, reviews, meetings=None):
    db.executescript("""
    CREATE TABLE course_numbers(uid TEXT PRIMARY KEY,number INTEGER);
    CREATE TABLE offerings(uid TEXT,term TEXT,PRIMARY KEY(uid,term));
    CREATE TABLE grade_summaries(uid TEXT,term TEXT,a INTEGER,ab INTEGER,b INTEGER,bc INTEGER,c INTEGER,d INTEGER,f INTEGER,PRIMARY KEY(uid,term));
    CREATE TABLE reviews(profile_id TEXT,review_id TEXT,course_uid TEXT,review_date TEXT,payload TEXT,PRIMARY KEY(profile_id,review_id));
    CREATE TABLE section_modes(uid TEXT,term TEXT,section_type TEXT,section_number TEXT,mode TEXT,PRIMARY KEY(uid,term,section_type,section_number,mode));
    CREATE TABLE class_meetings(uid TEXT,term TEXT,section_type TEXT,section_number TEXT,weekday INTEGER,start_minute INTEGER,end_minute INTEGER,PRIMARY KEY(uid,term,section_type,section_number,weekday,start_minute,end_minute));
    CREATE TABLE course_seasons(uid TEXT,season TEXT,PRIMARY KEY(uid,season));
    CREATE TABLE requisite_kinds(uid TEXT PRIMARY KEY,kind TEXT);
    CREATE TABLE course_designations(uid TEXT,family TEXT,value TEXT,label TEXT,PRIMARY KEY(uid,family,value));
    CREATE INDEX reviews_profile_date ON reviews(profile_id,review_date DESC,review_id);
    CREATE INDEX offerings_term ON offerings(term,uid);
    CREATE INDEX section_modes_lookup ON section_modes(term,mode,uid);
    CREATE INDEX class_meetings_lookup ON class_meetings(term,weekday,start_minute,uid);
    CREATE INDEX class_meetings_course_lookup ON class_meetings(uid,term,weekday,start_minute);
    CREATE INDEX course_seasons_lookup ON course_seasons(season,uid);
    CREATE INDEX course_designations_lookup ON course_designations(family,value,uid);
    """)
    sections_by_course = {}
    for uid, payload in db.execute("SELECT uid,payload FROM courses"):
        course = json.loads(payload)
        db.execute(
            "INSERT INTO course_numbers VALUES(?,?)", (uid, course.get("course_number"))
        )
        db.executemany(
            "INSERT OR IGNORE INTO offerings VALUES(?,?)",
            [(uid, row["term_id"]) for row in course.get("offerings") or []],
        )
        sections_by_course[uid] = course.get("sections") or []
        db.executemany(
            "INSERT OR IGNORE INTO section_modes VALUES(?,?,?,?,?)",
            section_mode_rows(uid, sections_by_course[uid]),
        )
        db.executemany(
            "INSERT OR IGNORE INTO course_seasons VALUES(?,?)",
            [(uid, season) for season in seasons_for(course)],
        )
        db.execute(
            "INSERT INTO requisite_kinds VALUES(?,?)",
            (uid, requisite_kind(course.get("requirements"))),
        )
        db.executemany(
            "INSERT OR IGNORE INTO course_designations VALUES(?,?,?,?)",
            designation_rows(uid, course.get("designations") or []),
        )
    db.executemany(
        "INSERT OR IGNORE INTO class_meetings VALUES(?,?,?,?,?,?,?)",
        class_meeting_rows(sections_by_course, meetings or ()),
    )
    columns = ",".join(
        f"COALESCE(json_extract(payload,'$.{key}'),0)" for key in GRADE_KEYS
    )
    db.execute(
        f"INSERT INTO grade_summaries SELECT uid,term,{columns} FROM grades WHERE section='' "
    )
    latest = {}
    for row in reviews:
        key = (row["source_instructor_id"], row["source_review_id"])
        if key not in latest or str(row["observed_at"]) > str(
            latest[key]["observed_at"]
        ):
            latest[key] = row
    db.executemany(
        "INSERT INTO reviews VALUES(?,?,?,?,?)",
        [
            (
                profile,
                review,
                row.get("course_uid"),
                str(row.get("review_date") or ""),
                json.dumps(row, default=str, ensure_ascii=False),
            )
            for (profile, review), row in latest.items()
        ],
    )


def section_mode_rows(uid, sections):
    rows = []
    for section in sections:
        mode = instruction_mode(section.get("instruction_mode"))
        if not mode or not section.get("term_id"):
            continue
        rows.append(
            (
                uid,
                section["term_id"],
                str(section.get("section_type") or ""),
                str(section.get("section_number") or ""),
                mode,
            )
        )
    return rows


def instruction_mode(raw):
    if not raw or not str(raw).strip():
        return None
    return INSTRUCTION_MODES.get(str(raw).strip().casefold(), "other")


def seasons_for(course):
    found = set()
    for offering in course.get("offerings") or []:
        found.update(seasons_in(offering.get("typically_offered")))
    return sorted(found)


def seasons_in(text):
    folded = str(text or "").casefold()
    return [season for season in ("fall", "spring", "summer") if season in folded]


def requisite_kind(requirements):
    """none: no course and no real condition. listed: at least one. unknown: not parsed."""
    if not isinstance(requirements, dict):
        return "unknown"
    status = requirements.get("status")
    if status == "needs_review":
        return "unknown"
    if status == "none":
        return "none"
    if status != "parsed":
        return "unknown"
    for node in requirements.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if node.get("course"):
            return "listed"
        condition = (
            " ".join(str(node.get("condition") or "").split()).casefold().rstrip(".")
        )
        if condition not in PLACEHOLDER_CONDITIONS:
            return "listed"
    return "none"


def designation_rows(uid, lines):
    rows = {}
    for line in lines:
        parsed = designation_parts(line)
        if parsed:
            family, value = parsed
            rows[(family, value)] = (uid, family, value, " ".join(str(line).split()))
    return list(rows.values())


def designation_parts(line):
    text = " ".join(str(line or "").split())
    if not text:
        return None
    if " - " in text:
        family, value = text.split(" - ", 1)
    else:
        family, value = text, "yes"
    family_key = " ".join(family.split()).casefold()
    value_key = " ".join(value.split()).casefold()
    if family_key == "comm qr":
        quantitative = QR_VALUE.fullmatch(value_key)
        communication = COMMUNICATION_VALUE.fullmatch(value_key)
        if quantitative:
            return "quantitative-reasoning", quantitative.group(1)
        if communication:
            return "communication", communication.group(1)
    slug_family = FAMILY_SLUGS.get(family_key, slug(family_key))
    if slug_family == "ethnic-studies" and slug(value_key) in {"ethnic-studies", "yes"}:
        return slug_family, "yes"
    if slug_family == "graduate-credit":
        return slug_family, "yes"
    return slug_family, slug(value_key)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.casefold().replace("&", " and ")).strip("-")


def class_meeting_rows(sections_by_course, meetings):
    collapsed = {}
    for meeting in meetings:
        if meeting.get("meeting_type") != "CLASS":
            continue
        uid = meeting.get("course_uid")
        if not uid:
            continue
        identity = meeting_section(meeting.get("name"))
        when = meeting_clock(meeting)
        if when is None:
            continue
        start, end = when
        term = term_for_meeting(
            sections_by_course.get(uid) or [], identity, start.date()
        )
        if not term:
            continue
        section_type, section_number = identity or ("", "")
        key = (
            uid,
            term,
            section_type,
            section_number,
            start.weekday(),
            start.hour * 60 + start.minute,
            end.hour * 60 + end.minute,
        )
        collapsed[key] = key
    return list(collapsed.values())


def meeting_section(name):
    match = MEETING_NAME.match(str(name or ""))
    if not match:
        return None
    return match.group(1), match.group(2)


def meeting_clock(meeting):
    start = clock(meeting.get("starts_at"))
    end = clock(meeting.get("ends_at"))
    if start is None or end is None:
        return None
    return start, end


def clock(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=CHICAGO)
    else:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone(CHICAGO)


def section_covers(section, day):
    start = clock(section.get("start_date"))
    end = clock(section.get("end_date"))
    if start is None or end is None:
        return False
    return start.date() <= day <= end.date()


def term_for_meeting(sections, identity, day):
    candidates = sections
    if identity:
        section_type, section_number = identity
        candidates = [
            section
            for section in sections
            if str(section.get("section_type") or "") == section_type
            and str(section.get("section_number") or "") == section_number
        ]
    terms = sorted(
        {
            section.get("term_id")
            for section in candidates
            if section.get("term_id") and section_covers(section, day)
        }
    )
    if len(terms) == 1:
        return terms[0]
    return None
