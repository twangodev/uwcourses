"""One source adapter per spider; all outbound ingestion goes through Scrapy."""

import json
import os
import re
from urllib.parse import parse_qs, urlparse

import scrapy
from scrapy.http import JsonRequest

from .models import CourseReference, digest
from .reconcile import plain


def item(kind, key, payload, response):
    return {
        "kind": kind,
        "key": str(key),
        "payload": payload,
        "source_url": response.url,
    }


class SourceSpider(scrapy.Spider):
    def __init__(self, store, run, **kwargs):
        super().__init__(**kwargs)
        self.store = store
        self.run_id = run
        self.semester = store.run(run)["semester"]
        self.failures = 0

    def failed(self, failure):
        self.failures += 1
        self.logger.error("Request failed: %s", failure.request.url)

    def request(self, url, callback, **kwargs):
        return scrapy.Request(url, callback=callback, errback=self.failed, **kwargs)


class CatalogSpider(SourceSpider):
    name = "catalog"
    allowed_domains = ["guide.wisc.edu"]

    async def start(self):
        yield self.request("https://guide.wisc.edu/sitemap.xml", self.sitemap)

    def sitemap(self, response):
        from scrapy.selector import Selector

        selector = Selector(text=response.body.decode(), type="xml")
        selector.remove_namespaces()
        urls = sorted(set(selector.css("loc::text").getall()))
        departments = [url for url in urls if re.search(r"/courses/.+", url)]
        if not departments:
            raise ValueError("Catalog sitemap contains no departments")
        for url in departments:
            yield self.request(url, self.department)

    def department(self, response):
        from bs4 import BeautifulSoup
        from uwcourses.course import Course

        soup = BeautifulSoup(response.body, "html.parser")
        title = soup.find(class_="page-title")
        match = re.fullmatch(
            r"(.*)\((.*)\)", title.get_text(strip=True) if title else ""
        )
        if not match:
            raise ValueError("Missing department heading")
        abbreviation = match[2].replace(" ", "")
        yield item("subjects", abbreviation, {"name": match[1].strip()}, response)
        blocks = soup.select("div.courseblock")
        if not blocks:
            content = soup.select_one("#textcontainer")
            empty_notice = f"The subject {abbreviation} does not have any active courses at time of Guide publication."
            if content and content.get_text(" ", strip=True) == empty_notice:
                return
            raise ValueError("Department contains no course blocks")
        for block in blocks:
            course = Course.from_block(block, self.logger)
            if course is None:
                raise ValueError("Could not parse course block")
            payload = plain(course)
            payload["course_reference"]["subjects"].sort()
            yield item(
                "courses", course.course_reference.get_identifier(), payload, response
            )


class MadgradesSpider(SourceSpider):
    name = "madgrades"
    allowed_domains = ["api.madgrades.com"]
    base = "https://api.madgrades.com/v1/"

    def request(self, url, callback, **kwargs):
        if (
            urlparse(url).hostname != "api.madgrades.com"
            or urlparse(url).scheme != "https"
        ):
            raise ValueError("Unexpected Madgrades URL")
        key = os.environ.get("MADGRADES_API_KEY")
        if not key:
            raise ValueError("MADGRADES_API_KEY is required")
        return super().request(
            url, callback, headers={"Authorization": f"Token token={key}"}, **kwargs
        )

    async def start(self):
        yield self.request(self.base + "terms", self.terms)
        yield self.request(self.base + "courses?per_page=100&page=1", self.courses)

    def terms(self, response):
        data = json.loads(response.body)
        if not data:
            raise ValueError("Empty Madgrades terms")
        for code, name in data.items():
            yield item("terms", code, {"name": name}, response)

    def courses(self, response):
        data = json.loads(response.body)
        page, total = int(data["currentPage"]), int(data["totalPages"])
        if not 1 <= page <= total or not data["results"]:
            raise ValueError("Invalid Madgrades pagination")
        if page == 1:
            for number in range(2, total + 1):
                yield self.request(
                    f"{self.base}courses?per_page=100&page={number}", self.courses
                )
        for course in data["results"]:
            reference = CourseReference(
                subjects=sorted(
                    {s["abbreviation"].replace(" ", "") for s in course["subjects"]}
                ),
                course_number=int(course["number"]),
            )
            yield self.request(
                course["url"] + "/grades",
                self.grades,
                cb_kwargs={
                    "reference": reference.model_dump(),
                    "source_id": str(course.get("uuid", course["url"])),
                },
            )

    def grades(self, response, reference, source_id):
        payload = json.loads(response.body)
        payload.update(course_reference=reference, source_id=source_id)
        yield item("grades", source_id, payload, response)


class EnrollmentSpider(SourceSpider):
    name = "enrollment"
    allowed_domains = ["public.enroll.wisc.edu"]
    base = "https://public.enroll.wisc.edu/api/search/v1"

    async def start(self):
        yield self.request(self.base + "/aggregate", self.terms)

    def terms(self, response):
        terms = json.loads(response.body)["terms"]
        selected = None
        for term in terms:
            code = str(term["termCode"])
            yield item(
                "terms",
                code,
                {
                    "name": term["shortDescription"],
                    "start": term["instructionBeginDate"],
                    "end": term["instructionEndDate"],
                },
                response,
            )
            if code == self.semester:
                selected = term
        if selected is None:
            raise ValueError(
                f"Semester {self.semester} is not available from enrollment API"
            )
        yield self.page(1)

    def page(self, page):
        return JsonRequest(
            self.base,
            data={
                "selectedTerm": self.semester,
                "queryString": "",
                "filters": [],
                "page": page,
                "pageSize": 100,
            },
            callback=self.hits,
            cb_kwargs={"page": page},
            errback=self.failed,
        )

    def hits(self, response, page):
        data = json.loads(response.body)
        found = int(data["found"])
        expected = min(100, found - (page - 1) * 100)
        if found <= 0 or len(data["hits"]) != expected:
            raise ValueError("Incomplete enrollment search page")
        if page == 1:
            for number in range(2, (found + 99) // 100 + 1):
                yield self.page(number)
        for hit in data["hits"]:
            subjects = (
                hit["allCrossListedSubjects"]
                if len(hit["allCrossListedSubjects"]) > 1
                else [hit["subject"]]
            )
            reference = CourseReference(
                subjects=sorted(
                    {s["shortDescription"].replace(" ", "") for s in subjects}
                ),
                course_number=int(hit["catalogNumber"]),
            )
            url = f"{self.base}/enrollmentPackages/{self.semester}/{hit['subject']['subjectCode']}/{hit['courseId']}"
            yield self.request(
                url,
                self.package,
                cb_kwargs={"hit": hit, "reference": reference.model_dump()},
            )

    def package(self, response, hit, reference):
        sections = json.loads(response.body)
        if not isinstance(sections, list):
            raise ValueError("Invalid enrollment package")
        key = f"{self.semester}:{hit['subject']['subjectCode']}:{hit['courseId']}"
        yield item(
            "offerings",
            key,
            {
                "term": self.semester,
                "course_reference": reference,
                "hit": hit,
                "sections": sections,
            },
            response,
        )
        for package in sections:
            for section in package["sections"]:
                for instructor in section.get("instructors", []):
                    name = f"{instructor['name']['first']} {instructor['name']['last']}"
                    yield item(
                        "instructors",
                        digest(name),
                        {"name": name, "email": instructor.get("email")},
                        response,
                    )


class InstructorSpider(SourceSpider):
    name = "instructors"
    allowed_domains = ["guide.wisc.edu", "www.ratemyprofessors.com"]

    async def start(self):
        yield self.request("https://guide.wisc.edu/faculty/", self.faculty)
        # Match the legacy direct public API client; scope this to RMP's
        # bootstrap/API endpoints rather than changing other sources' crawling.
        yield self.request(
            "https://www.ratemyprofessors.com/",
            self.authentication,
            meta={"dont_obey_robotstxt": True},
        )

    def faculty(self, response):
        from uwcourses.instructors import parse_faculty

        faculty = parse_faculty(response.body)
        if not faculty:
            raise ValueError("Faculty page contains no records")
        for name, (position, department, credentials) in faculty.items():
            yield item(
                "faculty",
                name,
                {
                    "name": name,
                    "position": position,
                    "department": department,
                    "credentials": credentials,
                },
                response,
            )

    def authentication(self, response):
        from .ratings import instructor_names, SEARCH_QUERY

        match = re.search(
            r'"REACT_APP_GRAPHQL_AUTH"\s*:\s*"([^"]+)"', response.body.decode()
        )
        if not match:
            raise ValueError("RMP authentication configuration missing")
        self.auth_header = {"Authorization": f"Basic {match[1]}"}
        names = instructor_names(self.store, self.run_id)
        if not names:
            raise ValueError("RMP collection has no instructor identities to query")
        for name in names:
            yield self.rating_request(
                SEARCH_QUERY,
                {
                    "query": {"text": name, "schoolID": "U2Nob29sLTE4NDE4"},
                    "after": None,
                },
                self.rating,
                name=name,
                candidates=[],
                cursors=[],
            )

    def rating_request(self, query, variables, callback, **context):
        return JsonRequest(
            "https://www.ratemyprofessors.com/graphql",
            data={"query": query, "variables": variables},
            headers=self.auth_header,
            callback=callback,
            cb_kwargs=context,
            errback=self.failed,
            dont_filter=True,
            meta={"dont_obey_robotstxt": True},
        )

    def rating(self, response, name, candidates=None, cursors=None):
        from .ratings import SEARCH_QUERY, next_cursor

        data = json.loads(response.body)
        if data.get("errors"):
            raise ValueError("RMP returned GraphQL errors")
        connection = data["data"]["newSearch"]["teachers"]
        candidates = list(candidates or [])
        known = {c["id"] for c in candidates}
        for edge in connection["edges"]:
            candidate = edge["node"]
            if candidate["id"] not in known:
                candidates.append(candidate)
                known.add(candidate["id"])
        cursors = list(cursors or [])
        cursor = next_cursor(connection, cursors[-1] if cursors else None)
        if cursor:
            if cursor in cursors:
                raise ValueError("RMP search pagination loop")
            yield self.rating_request(
                SEARCH_QUERY,
                {
                    "query": {"text": name, "schoolID": "U2Nob29sLTE4NDE4"},
                    "after": cursor,
                },
                self.rating,
                name=name,
                candidates=candidates,
                cursors=[*cursors, cursor],
            )
        else:
            yield from self.collect_reviews(response, name, candidates)

    def collect_reviews(self, response, name, candidates, index=0, cursors=None):
        from .ratings import REVIEWS_QUERY, next_cursor, matched_teacher, course_reviews

        while index < len(candidates):
            teacher = candidates[index]
            cursors = list(cursors or [])
            cursor = next_cursor(teacher["ratings"], cursors[-1] if cursors else None)
            if cursor:
                if cursor in cursors:
                    raise ValueError("RMP review pagination loop")
                yield self.rating_request(
                    REVIEWS_QUERY,
                    {"id": teacher["id"], "after": cursor},
                    self.review_page,
                    name=name,
                    candidates=candidates,
                    index=index,
                    cursors=[*cursors, cursor],
                )
                return
            index += 1
            cursors = []
        matched = matched_teacher(name, candidates)
        yield item(
            "ratings",
            name,
            {
                "name": name,
                "candidates": candidates,
                "collection_complete": True,
                "matched_teacher_id": matched["id"] if matched else None,
                "course_reviews": course_reviews(matched),
            },
            response,
        )

    def review_page(self, response, name, candidates, index, cursors):
        from .ratings import next_cursor

        data = json.loads(response.body)
        if data.get("errors"):
            raise ValueError("RMP returned GraphQL errors")
        teacher = data["data"]["node"]
        if teacher is None or teacher["id"] != candidates[index]["id"]:
            raise ValueError("RMP returned the wrong teacher")
        connection = teacher["ratings"]
        next_cursor(connection, cursors[-1])
        previous = candidates[index]["ratings"]
        known = {e["node"]["id"] for e in previous["edges"]}
        edges = list(previous["edges"])
        for edge in connection["edges"]:
            if edge["node"]["id"] not in known:
                edges.append(edge)
                known.add(edge["node"]["id"])
        candidates[index]["ratings"] = {**connection, "edges": edges}
        yield from self.collect_reviews(response, name, candidates, index, cursors)


class BuildingSpider(SourceSpider):
    name = "buildings"
    allowed_domains = ["map.wisc.edu", "www.map.wisc.edu"]

    async def start(self):
        yield self.request("https://map.wisc.edu/buildings/", self.directory)

    def directory(self, response):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.body, "html.parser")
        found = set()
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if len(cells) != 2:
                continue
            number = cells[1].get_text(strip=True)
            if not number:
                # Group entries such as Eagle Heights have no individual source ID.
                continue
            link = cells[0].find("a", href=True)
            url = response.urljoin(link["href"]) if link else ""
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in self.allowed_domains
                or parse_qs(parsed.query).get("initObj") != [number]
            ):
                raise ValueError(f"Invalid official building link: {number}")
            if number not in found:
                found.add(number)
                yield self.request(url, self.building, cb_kwargs={"number": number})
        if not found:
            raise ValueError("Campus building directory contains no building IDs")

    def building(self, response, number):
        from .buildings import validate_building

        # Building links use FP&M IDs; the embedded record exposes the separate
        # map-object ID, geometry and metadata without an extra API request.
        match = re.search(
            r"window\.Rails=(.*?);window\.W=", response.body.decode("utf-8"), re.S
        )
        if not match:
            raise ValueError("Missing campus map initialization data")
        data = json.loads(match[1]).get("init_obj")
        if not isinstance(data, dict) or data.get("building_number") != number:
            raise ValueError(f"Campus map did not resolve building {number}")
        validate_building(data)
        yield item("buildings", data["map_object_id"], data, response)


SPIDERS = {
    spider.name: spider
    for spider in (
        CatalogSpider,
        MadgradesSpider,
        EnrollmentSpider,
        InstructorSpider,
        BuildingSpider,
    )
}
