import os
import threading
from collections import defaultdict
from logging import getLogger

from bs4 import BeautifulSoup
from diskcache import Cache
from tqdm import tqdm

from uwcourses.course import Course
from uwcourses.enrollment_data import GradeData
from uwcourses.json_serializable import JsonSerializable


logger = getLogger(__name__)


class RMPData(JsonSerializable):
    def __init__(
        self,
        id,
        legacy_id,
        average_rating,
        average_difficulty,
        num_ratings,
        would_take_again_percent,
        mandatory_attendance,
        ratings_distribution,
        ratings,
    ):
        self.id = id
        self.legacy_id = legacy_id
        self.average_rating = average_rating
        self.average_difficulty = average_difficulty
        self.num_ratings = num_ratings
        self.would_take_again_percent = would_take_again_percent
        self.mandatory_attendance = mandatory_attendance
        self.ratings_distribution = ratings_distribution
        self.ratings = ratings

    @classmethod
    def from_json(cls, json_data):
        if not json_data:
            return None
        return RMPData(
            id=json_data["id"],
            legacy_id=json_data["legacy_id"],
            average_rating=json_data["average_rating"],
            average_difficulty=json_data["average_difficulty"],
            num_ratings=json_data["num_ratings"],
            would_take_again_percent=json_data["would_take_again_percent"],
            mandatory_attendance=json_data["mandatory_attendance"],
            ratings_distribution=json_data["ratings_distribution"],
            ratings=json_data["ratings"],
        )

    @classmethod
    def from_rmp_data(cls, rmp_data) -> "RMPData":
        id = rmp_data["id"]
        legacy_id = rmp_data["legacyId"]
        average_rating = rmp_data["avgRatingRounded"]
        average_difficulty = rmp_data["avgDifficultyRounded"]
        num_ratings = rmp_data["numRatings"]
        would_take_again_percent = rmp_data["wouldTakeAgainPercentRounded"]
        mandatory_attendance = rmp_data["mandatoryAttendance"]
        ratings_distribution = rmp_data["ratingsDistribution"]

        ratings = []
        for rating in rmp_data["ratings"]["edges"]:
            node = rating["node"]
            ratings.append(
                {
                    "comment": node["comment"],
                    "id": node.get("id"),
                    "course": node.get("class"),
                    "date": node.get("date"),
                    "quality_rating": node["qualityRating"],
                    "difficulty_rating": node["difficultyRatingRounded"],
                }
            )

        return RMPData(
            id=id,
            legacy_id=legacy_id,
            average_rating=average_rating,
            average_difficulty=average_difficulty,
            num_ratings=num_ratings,
            would_take_again_percent=would_take_again_percent,
            mandatory_attendance=mandatory_attendance,
            ratings_distribution=ratings_distribution,
            ratings=ratings,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "legacy_id": self.legacy_id,
            "average_rating": self.average_rating,
            "average_difficulty": self.average_difficulty,
            "num_ratings": self.num_ratings,
            "would_take_again_percent": self.would_take_again_percent,
            "mandatory_attendance": self.mandatory_attendance,
            "ratings_distribution": self.ratings_distribution,
            "ratings": self.ratings,
        }


class FullInstructor(JsonSerializable):
    def __init__(
        self,
        name,
        email,
        rmp_data: RMPData | None,
        position,
        department,
        credentials,
        official_name,
        courses_taught=None,
        cumulative_grade_data: GradeData | None = None,
    ):
        self.name = name
        self.email = email
        self.rmp_data = rmp_data
        self.position = position
        self.department = department
        self.credentials = credentials
        self.official_name = official_name
        self.courses_taught = courses_taught
        self.cumulative_grade_data = cumulative_grade_data

    @classmethod
    def from_json(cls, json_data) -> "FullInstructor":
        cumulative_grade_data = json_data.get("cumulative_grade_data", None)
        if cumulative_grade_data:
            cumulative_grade_data = GradeData.from_json(cumulative_grade_data)

        courses_taught = json_data.get("courses_taught", None)
        if courses_taught:
            courses_taught = {
                Course.Reference.from_json(course_ref) for course_ref in courses_taught
            }

        return FullInstructor(
            name=json_data["name"],
            email=json_data["email"],
            rmp_data=RMPData.from_json(json_data["rmp_data"]),
            position=json_data["position"],
            department=json_data["department"],
            credentials=json_data["credentials"],
            official_name=json_data["official_name"],
            courses_taught=courses_taught,
            cumulative_grade_data=cumulative_grade_data,
        )

    def to_dict(self):
        return {
            "name": self.name,
            "email": self.email,
            "rmp_data": self.rmp_data.to_dict() if self.rmp_data else None,
            "position": self.position,
            "department": self.department,
            "credentials": self.credentials,
            "official_name": self.official_name,
            "courses_taught": [
                course_ref.to_dict() for course_ref in self.courses_taught
            ]
            if self.courses_taught
            else None,
            "cumulative_grade_data": self.cumulative_grade_data.to_dict()
            if self.cumulative_grade_data
            else None,
        }


def parse_faculty(content):
    """Parse faculty records without performing a request."""
    soup = BeautifulSoup(content, "html.parser")
    uw_people_lists = soup.find_all("ul", class_="uw-people")

    faculty = {}

    for ul in uw_people_lists:
        for li in ul.find_all("li"):
            name = (
                li.find("span", class_="faculty-name").text
                if li.find("span", class_="faculty-name")
                else None
            )

            if not name:
                continue

            details = li.get_text(separator="\n").split("\n")
            position = details[1] if len(details) > 1 else None
            department = details[2] if len(details) > 2 else None
            credentials = details[3] if len(details) > 3 else None

            faculty[name] = (position, department, credentials)

    return faculty


_caches: dict[str, Cache] = {}
_caches_lock = threading.Lock()


def get_match_cache(cache_dir: str) -> Cache:
    # build one canonical directory for your cache
    path = os.path.abspath(os.path.join(cache_dir, "name_cache"))
    os.makedirs(path, exist_ok=True)

    with _caches_lock:
        cache = _caches.get(path)
        if cache is None:
            cache = Cache(path)
            _caches[path] = cache
    return cache


null_sentinel = object()


def merge_instructors(
    additional_instructors, instructors, course_ref_to_course, cache_dir
):
    instructor_appearances: dict[str, list[tuple[Course.Reference, str]]] = defaultdict(
        list
    )
    for course_ref, course in course_ref_to_course.items():
        for term, term_data in course.term_data.items():
            if term_data.grade_data:
                for instr in term_data.grade_data.instructors:
                    instructor_appearances[instr].append((course_ref, term))

    from uwcourses.name_matcher import iter_name_matches
    from uwcourses.models import digest

    # Stable ordering preserves reproducible tie-breaking. Candidate identity is
    # part of the cache key so changed rosters cannot reuse stale matches.
    candidates = sorted(instructors)
    cache = get_match_cache(cache_dir)
    prefix = "indexed-v1:" + digest(candidates) + ":"
    matches, pending = {}, []
    for name in sorted(additional_instructors):
        value = cache.get(prefix + name, default=null_sentinel)
        if value is null_sentinel:
            pending.append(name)
        else:
            matches[name] = value
    for name, match in tqdm(
        iter_name_matches(pending, candidates),
        total=len(pending),
        desc="Match instructor names",
        unit="instructor",
    ):
        matches[name] = match
        cache.set(prefix + name, match)
    for instructor, match in matches.items():
        if match and match != instructor:
            for course_ref, term in instructor_appearances.get(instructor, []):
                grades = course_ref_to_course[course_ref].term_data[term].grade_data
                grades.instructors.remove(instructor)
                grades.instructors.add(match)
        elif match is None:
            instructors[instructor] = None
