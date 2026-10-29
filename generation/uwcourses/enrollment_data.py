from logging import getLogger

from uwcourses.json_serializable import JsonSerializable
from uwcourses.safe_parse import safe_int

logger = getLogger(__name__)


class EnrollmentData(JsonSerializable):
    class School(JsonSerializable):
        def __init__(self, name, abbreviation, url):
            self.name = name
            self.abbreviation = abbreviation
            self.url = url

        @classmethod
        def from_json(cls, data) -> "EnrollmentData.School":
            return EnrollmentData.School(
                name=data["name"], abbreviation=data["abbreviation"], url=data["url"]
            )

        def to_dict(self) -> dict:
            return {
                "name": self.name,
                "abbreviation": self.abbreviation,
                "url": self.url,
            }

        @classmethod
        def from_enrollment(cls, data) -> "EnrollmentData.School":
            return EnrollmentData.School(
                name=data["shortDescription"],
                abbreviation=data["academicOrgCode"],
                url=data["schoolCollegeURI"],
            )

        def __str__(self):
            return self.name

        def __eq__(self, other):
            return (
                self.name == other.name
                and self.abbreviation == other.abbreviation
                and self.url == other.url
            )

    def __init__(
        self,
        school: School | None,
        last_taught_term: str,
        typically_offered: str,
        credit_count: tuple[int, int],
        general_education: bool,
        ethnics_studies: bool,
        instructors,
    ):
        self.school = school
        self.last_taught_term = last_taught_term
        self.typically_offered = typically_offered
        self.credit_count = credit_count
        self.general_education = general_education
        self.ethnics_studies = ethnics_studies
        self.instructors = instructors

    class MeetingLocation(JsonSerializable):
        # Class-level dict to track all unique meeting locations for O(1) lookup
        _all_locations = {}

        def __init__(self, building, room, coordinates, capacity=None):
            self.building = building
            self.room = room
            self.coordinates = coordinates
            self.capacity = capacity

        @classmethod
        def get_or_create_with_capacity(
            cls, building, room, coordinates, class_capacity
        ):
            """
            Get existing MeetingLocation or create new one, updating max capacity.

            Args:
                building: Building name
                room: Room identifier
                coordinates: Tuple of (latitude, longitude)
                class_capacity: Current class capacity (used to estimate room capacity)

            Returns:
                MeetingLocation instance with updated max capacity
            """
            # Create a key for dictionary lookup using the same hash logic
            location_key = (building, room, coordinates)

            # O(1) lookup in dictionary
            if location_key in cls._all_locations:
                existing_location = cls._all_locations[location_key]
                # Update capacity to maximum seen so far
                if existing_location.capacity is None or (
                    class_capacity is not None
                    and class_capacity > existing_location.capacity
                ):
                    existing_location.capacity = class_capacity
                return existing_location
            else:
                # Create new location and add to dictionary
                new_location = cls(building, room, coordinates, class_capacity)
                cls._all_locations[location_key] = new_location
                return new_location

        @classmethod
        def from_json(cls, data) -> "EnrollmentData.MeetingLocation":
            coordinates = data["coordinates"]
            return cls.get_or_create_with_capacity(
                building=data["building"],
                room=data["room"],
                coordinates=(coordinates[0], coordinates[1]) if coordinates else None,
                class_capacity=data.get("capacity"),
            )

        def to_dict(self) -> dict:
            return {
                "building": self.building,
                "room": self.room,
                "coordinates": self.coordinates,
                "capacity": self.capacity,
            }

        def __eq__(self, other):
            if not isinstance(other, EnrollmentData.MeetingLocation):
                return False
            return (
                self.building == other.building
                and self.room == other.room
                and self.coordinates == other.coordinates
            )

        def __hash__(self):
            return hash((self.building, self.room, self.coordinates))

    class Meeting(JsonSerializable):
        def __init__(
            self,
            name,
            type,
            start_time,
            end_time,
            location,
            current_enrollment,
            instructors=None,
            course_reference=None,
        ):
            self.name = name
            self.type = type
            self.start_time = start_time
            self.end_time = end_time
            self.location = location
            self.current_enrollment = current_enrollment
            self.instructors = instructors or []
            self.course_reference = course_reference

        @classmethod
        def from_json(cls, data) -> "EnrollmentData.Meeting":
            course_reference = None
            if data.get("course_reference"):
                from uwcourses.course import Course

                course_reference = Course.Reference.from_json(data["course_reference"])

            return EnrollmentData.Meeting(
                name=data["name"],
                type=data["type"],
                start_time=data["start_time"],
                end_time=data["end_time"],
                location=EnrollmentData.MeetingLocation.from_json(data["location"])
                if data.get("location")
                else None,
                current_enrollment=data.get("current_enrollment"),
                instructors=data.get("instructors", []),
                course_reference=course_reference,
            )

        def to_dict(self) -> dict:
            return {
                "name": self.name,
                "type": self.type,
                "start_time": self.start_time,
                "end_time": self.end_time,
                "location": self.location.to_dict() if self.location else None,
                "current_enrollment": self.current_enrollment,
                "instructors": self.instructors,
                "course_reference": self.course_reference.to_dict()
                if self.course_reference
                else None,
            }

        def __eq__(self, other):
            if not isinstance(other, EnrollmentData.Meeting):
                return False

            # Extract section identifier (e.g., "LEC 002" from "LEC 002 #9")
            self_section = self.name.split("#")[0].strip() if self.name else ""
            other_section = other.name.split("#")[0].strip() if other.name else ""

            # Compare key identifying attributes
            # Note: We don't include course_reference to allow deduplication across cross-listed courses
            return (
                self_section == other_section
                and self.type == other.type
                and self.start_time == other.start_time
                and self.end_time == other.end_time
                and sorted(self.instructors) == sorted(other.instructors)
            )

        def __hash__(self):
            # Extract section identifier for hashing
            section = self.name.split("#")[0].strip() if self.name else ""

            # Create a hashable representation of the meeting
            return hash(
                (
                    section,
                    self.type,
                    self.start_time,
                    self.end_time,
                    tuple(sorted(self.instructors)),
                )
            )

    @classmethod
    def from_json(cls, data) -> "EnrollmentData":
        return EnrollmentData(
            school=EnrollmentData.School.from_json(data["school"]),
            last_taught_term=data["last_taught_term"],
            typically_offered=data["typically_offered"],
            credit_count=(data["credit_count"][0], data["credit_count"][1]),
            general_education=data["general_education"],
            ethnics_studies=data["ethnics_studies"],
            instructors=data["instructors"],
        )

    @classmethod
    def from_enrollment(cls, data, terms) -> "EnrollmentData":
        last_taught_term_code = safe_int(data["lastTaught"])
        last_taught_term = None
        if last_taught_term_code and last_taught_term_code in terms:
            last_taught_term = terms[last_taught_term_code]
        return EnrollmentData(
            school=EnrollmentData.School.from_enrollment(
                data["subject"]["schoolCollege"]
            ),
            last_taught_term=last_taught_term,
            typically_offered=data["typicallyOffered"],
            credit_count=(data["minimumCredits"], data["maximumCredits"]),
            general_education=data["generalEd"] is not None,
            ethnics_studies=data["ethnicStudies"] is not None,
            instructors={},
        )

    def to_dict(self) -> dict:
        return {
            "school": self.school.to_dict(),
            "last_taught_term": self.last_taught_term,
            "typically_offered": self.typically_offered,
            "credit_count": [self.credit_count[0], self.credit_count[1]],
            "general_education": self.general_education,
            "ethnics_studies": self.ethnics_studies,
            "instructors": self.instructors,
        }


class GradeData(JsonSerializable):
    def __init__(
        self,
        total,
        a,
        ab,
        b,
        bc,
        c,
        d,
        f,
        satisfactory,
        unsatisfactory,
        credit,
        no_credit,
        passed,
        incomplete,
        no_work,
        not_reported,
        other,
        instructors: set[str] | None,
    ):
        self.total = total
        self.a = a
        self.ab = ab
        self.b = b
        self.bc = bc
        self.c = c
        self.d = d
        self.f = f
        self.satisfactory = satisfactory
        self.unsatisfactory = unsatisfactory
        self.credit = credit
        self.no_credit = no_credit
        self.passed = passed
        self.incomplete = incomplete
        self.no_work = no_work
        self.not_reported = not_reported
        self.other = other
        self.instructors = instructors

    @classmethod
    def empty(cls):
        return GradeData(
            total=0,
            a=0,
            ab=0,
            b=0,
            bc=0,
            c=0,
            d=0,
            f=0,
            satisfactory=0,
            unsatisfactory=0,
            credit=0,
            no_credit=0,
            passed=0,
            incomplete=0,
            no_work=0,
            not_reported=0,
            other=0,
            instructors=set(),
        )

    @classmethod
    def from_madgrades(cls, json_data) -> "GradeData":
        return GradeData(
            total=json_data["total"],
            a=json_data["aCount"],
            ab=json_data["abCount"],
            b=json_data["bCount"],
            bc=json_data["bcCount"],
            c=json_data["cCount"],
            d=json_data["dCount"],
            f=json_data["fCount"],
            satisfactory=json_data["sCount"],
            unsatisfactory=json_data["uCount"],
            credit=json_data["crCount"],
            no_credit=json_data["nCount"],
            passed=json_data["pCount"],
            incomplete=json_data["iCount"],
            no_work=json_data["nwCount"],
            not_reported=json_data["nrCount"],
            other=json_data["otherCount"],
            instructors=None,
        )

    @classmethod
    def from_json(cls, json_data) -> "GradeData":
        return GradeData(
            total=json_data["total"],
            a=json_data["a"],
            ab=json_data["ab"],
            b=json_data["b"],
            bc=json_data["bc"],
            c=json_data["c"],
            d=json_data["d"],
            f=json_data["f"],
            satisfactory=json_data["satisfactory"],
            unsatisfactory=json_data["unsatisfactory"],
            credit=json_data["credit"],
            no_credit=json_data["no_credit"],
            passed=json_data["passed"],
            incomplete=json_data["incomplete"],
            no_work=json_data["no_work"],
            not_reported=json_data["not_reported"],
            other=json_data["other"],
            instructors=set(json_data["instructors"])
            if json_data["instructors"]
            else None,
        )

    def to_dict(self):
        return {
            "total": self.total,
            "a": self.a,
            "ab": self.ab,
            "b": self.b,
            "bc": self.bc,
            "c": self.c,
            "d": self.d,
            "f": self.f,
            "satisfactory": self.satisfactory,
            "unsatisfactory": self.unsatisfactory,
            "credit": self.credit,
            "no_credit": self.no_credit,
            "passed": self.passed,
            "incomplete": self.incomplete,
            "no_work": self.no_work,
            "not_reported": self.not_reported,
            "other": self.other,
            "instructors": list(self.instructors) if self.instructors else None,
        }


class MadgradesData:
    def __init__(self, cumulative, by_term: dict[str, GradeData]):
        self.cumulative = cumulative
        self.by_term = by_term

    @classmethod
    def from_response(cls, data):
        """Parse an archived or freshly fetched Madgrades response."""
        cumulative = GradeData.from_madgrades(data["cumulative"])
        course_offerings = data["courseOfferings"]

        by_term = {}
        for offering in course_offerings:
            term_code = str(offering["termCode"])
            grade_data = GradeData.from_madgrades(offering["cumulative"])

            instructors = set()
            sections = offering["sections"]

            for section in sections:
                for instructor in section["instructors"]:
                    instructors.add(instructor["name"])

            grade_data.instructors = instructors

            by_term[term_code] = grade_data

        return MadgradesData(cumulative=cumulative, by_term=by_term)


class TermData(JsonSerializable):
    def __init__(
        self,
        enrollment_data: EnrollmentData | None,
        grade_data: GradeData | None,
    ):
        self.enrollment_data = enrollment_data
        self.grade_data = grade_data

    @classmethod
    def from_json(cls, data) -> "TermData":
        enrollment_data = None
        if data["enrollment_data"]:
            enrollment_data = EnrollmentData.from_json(data["enrollment_data"])
        grade_data = None
        if data["grade_data"]:
            grade_data = GradeData.from_json(data["grade_data"])
        return TermData(
            enrollment_data=enrollment_data,
            grade_data=grade_data,
        )

    def to_dict(self) -> dict:
        return {
            "enrollment_data": self.enrollment_data.to_dict()
            if self.enrollment_data
            else None,
            "grade_data": self.grade_data.to_dict() if self.grade_data else None,
        }
