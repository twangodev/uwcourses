"""Validated boundaries between source parsers and storage."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal[
        "subjects",
        "courses",
        "terms",
        "grades",
        "offerings",
        "instructors",
        "faculty",
        "ratings",
        "buildings",
    ]
    key: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    payload: dict[str, Any]


class CourseReference(BaseModel):
    model_config = ConfigDict(strict=True)
    subjects: list[str] = Field(min_length=1)
    course_number: int = Field(ge=0)

    @property
    def identifier(self):
        return f"{'/'.join(sorted(set(self.subjects)))} {self.course_number}"


class CatalogCourse(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    course_reference: CourseReference
    course_title: str = Field(min_length=1)
    description: str


def validate_record(record):
    record = Record.model_validate(record)
    if record.kind == "courses":
        course = CatalogCourse.model_validate(record.payload)
        if course.course_reference.identifier != record.key:
            raise ValueError("Course key does not match its reference")
    elif record.kind in {"subjects", "terms", "instructors"}:
        if (
            not isinstance(record.payload.get("name"), str)
            or not record.payload["name"].strip()
        ):
            raise ValueError(f"Missing name for {record.kind}")
    elif record.kind == "offerings":
        if not isinstance(record.payload.get("sections"), list):
            raise ValueError("Enrollment package must contain a sections list")
        CourseReference.model_validate(record.payload.get("course_reference"))
    elif record.kind == "grades":
        CourseReference.model_validate(record.payload.get("course_reference"))
        if not isinstance(record.payload.get("courseOfferings"), list):
            raise ValueError("Missing Madgrades offerings")
        if not isinstance(record.payload.get("cumulative"), dict):
            raise ValueError("Missing cumulative grades")
    elif record.kind == "buildings":
        from .buildings import validate_building

        validate_building(record.payload)
        if record.key != str(record.payload["map_object_id"]):
            raise ValueError("Building key does not match map object ID")
    canonical(record.payload)
    return record
