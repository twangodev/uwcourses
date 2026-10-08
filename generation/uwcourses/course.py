import re
from logging import Logger

from bs4 import NavigableString

from uwcourses.enrollment_data import GradeData, TermData
from uwcourses.json_serializable import JsonSerializable
from uwcourses.requirement_ast import (
    RequirementAbstractSyntaxTree,
    tokenize_requisites,
    RequirementParser,
)


def remove_extra_spaces(text: str):
    return re.sub(r"\s+", " ", text).strip()


def designation_lines(data):
    """Course Designation values are one catalog line per <br>."""
    if data is None:
        return []
    lines, buffer = [], []

    def flush():
        line = remove_extra_spaces("".join(buffer))
        if line:
            lines.append(line)
        buffer.clear()

    for node in data.children:
        if getattr(node, "name", None) == "br":
            flush()
        else:
            buffer.append(node.get_text() if hasattr(node, "get_text") else str(node))
    flush()
    return lines


def cleanup_course_reference_str(course_code: str):
    """Remove special HTML characters and clean up the course code."""
    if not course_code:
        return None
    course_code = remove_extra_spaces(course_code)
    return course_code.replace("\u200b", " ").replace("\u00a0", " ").strip()


class Identifiable:
    def get_identifier(self) -> str:
        raise NotImplementedError


class Course(JsonSerializable):
    class Reference(JsonSerializable, Identifiable):
        def __init__(self, subjects: set[str], course_number: int):
            self.subjects = subjects
            self.course_number = course_number

        @classmethod
        def from_json(cls, json_data) -> "Course.Reference":
            return Course.Reference(
                subjects=set(json_data["subjects"]),
                course_number=json_data["course_number"],
            )

        @classmethod
        def from_string(cls, course_reference_str: str):
            course_reference_str = cleanup_course_reference_str(course_reference_str)
            match = re.match(r"(\D+)(\d+)", course_reference_str)
            course_subject_str = (
                match.group(1).replace(" ", "").strip()
            )  # Only keep the subject
            raw_course_subjects = course_subject_str.split("/")
            course_subject = {
                str(subject).replace(" ", "") for subject in raw_course_subjects
            }
            course_number = int(match.group(2).strip())  # Convert to integer
            return Course.Reference(course_subject, course_number)

        def to_dict(self):
            return {
                "subjects": list(self.subjects),
                "course_number": self.course_number,
            }

        def get_identifier(self) -> str:
            subjects = "/".join(sorted(self.subjects))
            return f"{subjects} {self.course_number}"

        def __eq__(self, other):
            if not isinstance(other, Course.Reference):
                return False
            return (
                self.subjects == other.subjects
                and self.course_number == other.course_number
            )

        def __hash__(self):
            return hash(self.get_identifier())

        def __repr__(self):
            return f"CourseReference(subjects={self.subjects}, course_number={self.course_number})"

        def __str__(self):
            return self.get_identifier()

    class Prerequisites(JsonSerializable):
        def __init__(
            self,
            prerequisites_text,
            linked_requisite_text,
            course_references,
            abstract_syntax_tree,
        ):
            self.prerequisites_text = prerequisites_text
            self.linked_requisite_text = linked_requisite_text
            self.course_references = course_references
            self.abstract_syntax_tree = abstract_syntax_tree

        @classmethod
        def from_json(cls, json_data) -> "Course.Prerequisites":
            return Course.Prerequisites(
                prerequisites_text=json_data["prerequisites_text"],
                linked_requisite_text=json_data["linked_requisite_text"],
                course_references=[
                    Course.Reference.from_json(course_ref)
                    for course_ref in json_data["course_references"]
                ],
                abstract_syntax_tree=RequirementAbstractSyntaxTree.from_json(
                    json_data["abstract_syntax_tree"]
                ),
            )

        def to_dict(self):
            return {
                "prerequisites_text": self.prerequisites_text,
                "linked_requisite_text": self.linked_requisite_text,
                "course_references": [
                    course_ref.to_dict() for course_ref in self.course_references
                ],
                "abstract_syntax_tree": self.abstract_syntax_tree.to_dict()
                if self.abstract_syntax_tree
                else None,
            }

        def __eq__(self, other):
            if not isinstance(other, Course.Prerequisites):
                return False
            return (
                self.prerequisites_text == other.prerequisites_text
                and self.course_references == other.course_references
            )

    def __init__(
        self,
        course_reference: Reference,
        course_title: str,
        description: str,
        prerequisites: Prerequisites,
        optimized_prerequisites: list[Reference] | None,
        cumulative_grade_data: "GradeData | None",
        term_data: dict[str, TermData],
        similar_courses=None,
        keywords=None,
        satisfies: set[Reference] = None,
        has_meetings: bool = False,
        designations: list[str] | None = None,
        official_learning_outcomes: list[dict] | None = None,
    ):
        if similar_courses is None:
            similar_courses = set()

        if keywords is None:
            keywords = []

        if satisfies is None:
            satisfies = set()

        self.course_reference = course_reference
        self.course_title = course_title
        self.description = description
        self.prerequisites = prerequisites
        self.optimized_prerequisites = optimized_prerequisites
        self.cumulative_grade_data = cumulative_grade_data
        self.term_data = term_data
        self.similar_courses = similar_courses
        self.keywords = keywords
        self.satisfies = satisfies
        self.has_meetings = has_meetings
        self.designations = list(designations or [])
        self.official_learning_outcomes = list(official_learning_outcomes or [])

    @classmethod
    def from_json(cls, json_data) -> "Course":
        optimized_prerequisites = None
        if json_data["optimized_prerequisites"]:
            optimized_prerequisites = [
                Course.Reference.from_json(json)
                for json in json_data["optimized_prerequisites"]
            ]

        cumulative_grade_data = None
        if json_data["cumulative_grade_data"]:
            cumulative_grade_data = GradeData.from_json(
                json_data["cumulative_grade_data"]
            )

        return Course(
            course_reference=Course.Reference.from_json(json_data["course_reference"]),
            course_title=json_data["course_title"],
            description=json_data["description"],
            prerequisites=Course.Prerequisites.from_json(json_data["prerequisites"]),
            optimized_prerequisites=optimized_prerequisites,
            cumulative_grade_data=cumulative_grade_data,
            term_data={
                term: TermData.from_json(data)
                for term, data in json_data["term_data"].items()
            },
            similar_courses={
                Course.Reference.from_json(course_ref)
                for course_ref in json_data["similar_courses"]
            }
            if json_data.get("similar_courses", None)
            else set(),
            keywords=json_data.get("keywords", []),
            satisfies={
                Course.Reference.from_json(ref)
                for ref in json_data.get("satisfies", [])
            },
            has_meetings=json_data.get("has_meetings", False),
            designations=json_data.get("designations") or [],
            official_learning_outcomes=json_data.get("official_learning_outcomes")
            or [],
        )

    def to_dict(self):
        return {
            "course_reference": self.course_reference.to_dict(),
            "course_title": self.course_title,
            "description": self.description,
            "prerequisites": self.prerequisites.to_dict(),
            "optimized_prerequisites": [
                course_ref.to_dict() for course_ref in self.optimized_prerequisites
            ]
            if self.optimized_prerequisites
            else None,
            "cumulative_grade_data": self.cumulative_grade_data.to_dict()
            if self.cumulative_grade_data
            else None,
            "term_data": {
                term: data.to_dict() for term, data in self.term_data.items()
            },
            "similar_courses": [
                course_ref.to_dict() for course_ref in self.similar_courses
            ],
            "keywords": self.keywords,
            "satisfies": [ref.to_dict() for ref in self.satisfies],
            "has_meetings": self.has_meetings,
            "designations": self.designations,
            "official_learning_outcomes": self.official_learning_outcomes,
        }

    @classmethod
    def from_block(
        cls,
        block,
        logger: Logger,
        *,
        source_url=None,
        observed_at=None,
        catalog_year=None,
    ):
        from .learning_outcomes import catalog_outcomes

        # Callers without source context remain compatible, without inventing a URL.
        outcomes = (
            catalog_outcomes(
                block,
                source_url=source_url,
                observed_at=observed_at,
                catalog_year=catalog_year,
            )
            if source_url
            else []
        )
        html_title = block.find("p", class_="courseblocktitle noindent")

        if not html_title:
            return None

        course_reference_str = html_title.find(
            "span", class_="courseblockcode"
        ).get_text(strip=True)
        if not course_reference_str:
            return None
        course_reference = Course.Reference.from_string(course_reference_str)

        raw_title = html_title.get_text(strip=True)
        raw_course_title = raw_title.replace(course_reference_str, "").strip()
        course_title = (
            raw_course_title.split("—", 1)[-1].strip()
            if "—" in raw_course_title
            else raw_course_title
        )

        description = block.find("p", class_="courseblockdesc noindent").get_text(
            strip=True
        )

        cb_extras = block.find("div", class_="cb-extras")
        designations = []
        requisites_data = None
        if cb_extras:
            designation_header = cb_extras.find(
                "span",
                class_="cbextra-label",
                string=re.compile(r"Course Designation:"),
            )
            if designation_header:
                designations = designation_lines(
                    designation_header.find_next("span", class_="cbextra-data")
                )
            requisites_header = cb_extras.find(
                "span", class_="cbextra-label", string=re.compile("Requisites:")
            )
            if requisites_header:
                requisites_data = requisites_header.find_next(
                    "span", class_="cbextra-data"
                )
        if requisites_data is None:
            return Course(
                course_reference,
                course_title,
                description,
                Course.Prerequisites("", [], set(), None),
                None,
                None,
                {},
                designations=designations,
                official_learning_outcomes=outcomes,
            )
        requisites_text = requisites_data.get_text(strip=True)

        requisites_courses = set()
        linked_requisite_text = []

        for node in requisites_data.contents:
            if isinstance(node, NavigableString):
                linked_requisite_text.append(node.get_text())
            elif node.name == "a":
                title = node.get("title", "").strip()
                reference = Course.Reference.from_string(title)

                requisites_courses.add(reference)
                linked_requisite_text.append(reference)
            else:
                linked_requisite_text.append(node.get_text(strip=True))

        tokens = tokenize_requisites(linked_requisite_text)

        parser = RequirementParser(tokens)
        tree = None
        try:
            tree = parser.parse()
        except SyntaxError as se:
            logger.warning(
                f"Syntax error in course {course_reference}: {se}. See text: {requisites_text}"
            )

        requisites_courses.discard(course_reference)  # Remove self-reference

        course_prerequisite = Course.Prerequisites(
            requisites_text, linked_requisite_text, requisites_courses, tree
        )
        return Course(
            course_reference,
            course_title,
            description,
            course_prerequisite,
            None,
            None,
            {},
            designations=designations,
            official_learning_outcomes=outcomes,
        )

    def determine_parent(self):
        parent = None
        subjects = self.course_reference.subjects
        if len(subjects) > 1:
            parent = "CROSSLISTED"
        elif len(subjects) == 1:
            parent = next(iter(subjects))
        return parent

    def get_identifier(self):
        return self.course_reference.get_identifier()

    def get_short_summary(self):
        return f"""Course Title: {self.course_reference.get_identifier()} - {self.course_title}
        Course Description: {self.description}
        """

    def get_full_summary(self):
        req = self.prerequisites.prerequisites_text
        return f"""{self.get_short_summary()}
        Prerequisites: {req}
        """

    def get_latest_term_data(self):
        """
        Get the latest term data for the course.
        """
        if not self.term_data:
            return None
        latest_term = max(self.term_data.keys(), key=lambda x: int(x))
        return self.term_data[latest_term]

    def __eq__(self, other):
        return (
            self.get_identifier() == other.get_identifier()
            and self.course_title == other.course_title
            and self.description == other.description
        )

    def __hash__(self):
        return hash(self.get_identifier())

    def __repr__(self):
        return self.get_identifier()
