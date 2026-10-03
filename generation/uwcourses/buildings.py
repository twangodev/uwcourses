"""Official campus-map records, with source geometry and identity intact."""

import json
import math

import pyarrow as pa

from .models import canonical


SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("source_observed_at", pa.timestamp("us", tz="UTC")),
        ("source_url", pa.string()),
        ("content_hash", pa.string()),
        ("building_uid", pa.string()),
        ("map_object_id", pa.int64()),
        ("building_number", pa.string()),
        ("object_type", pa.string()),
        ("name", pa.string()),
        ("street_address", pa.string()),
        ("description", pa.string()),
        ("hours", pa.string()),
        ("latitude", pa.float64()),
        ("longitude", pa.float64()),
        ("geometry_json", pa.string()),
        ("meta_json", pa.string()),
    ]
)
DESCRIPTION = (
    "Official map.wisc.edu buildings in the selected source snapshot. Map object IDs "
    "and FP&M building numbers are distinct source identities; building numbers are "
    "strings retaining leading zeros and suffixes. Geometry is source GeoJSON in "
    "longitude/latitude order, including holes and multipolygons. Null geometry "
    "means unavailable. Observation timestamps and URLs preserve provenance; full "
    "source records and historical observations remain in archive_observations. "
    "These records do not infer course-location identity. Older snapshots may be empty."
)
HISTORY_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("source", pa.string()),
        ("kind", pa.string()),
        ("entity_id", pa.string()),
        ("source_url", pa.string()),
        ("observed_at", pa.timestamp("us", tz="UTC")),
        ("content_hash", pa.string()),
        ("payload_json", pa.string()),
    ]
)
HISTORY_DESCRIPTION = (
    "Complete official campus-map observations across snapshots, including source "
    "metadata and image URLs in payload_json. observed_at is the observation timestamp, "
    "not an inferred validity interval. entity_id is the map-object ID; FP&M building "
    "numbers remain strings in the payload. buildings_current selects the map snapshot "
    "used by this release. Supplemental building publications can extend an existing "
    "course release without replacing its course or enrichment snapshot."
)


def building_observations(db):
    from .public_data import timestamp

    for row in db.execute(
        "SELECT * FROM observations WHERE source='buildings' AND kind='buildings' "
        "ORDER BY run_id,entity_id"
    ):
        value = dict(row)
        value["observed_at"] = timestamp(value["observed_at"])
        yield value


def position(value):
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(n) not in (float, int) or not math.isfinite(n) for n in value)
        or not -180 <= value[0] <= 180
        or not -90 <= value[1] <= 90
    ):
        raise ValueError("Invalid building longitude/latitude")
    return value


def polygon(rings):
    if not isinstance(rings, list) or not rings:
        raise ValueError("Missing building polygon rings")
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("Invalid building polygon ring")
        for point in ring:
            position(point)


def validate_building(data):
    identifier = data.get("map_object_id")
    if type(identifier) is not int or identifier <= 0 or data.get("id") != identifier:
        raise ValueError("Invalid campus map object ID")
    if data.get("object_type") not in {"building", "building_partial"}:
        raise ValueError("Campus map record is not a building")
    for field in ("name", "building_number"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Missing building {field}")
    position(data.get("lnglat"))
    geometry = data.get("geojson")
    if geometry is not None:
        if not isinstance(geometry, dict):
            raise ValueError("Invalid building GeoJSON")
        kind, coordinates = geometry.get("type"), geometry.get("coordinates")
        if kind == "Polygon":
            polygon(coordinates)
        elif kind == "MultiPolygon" and isinstance(coordinates, list) and coordinates:
            for rings in coordinates:
                polygon(rings)
        elif kind == "Point":
            position(coordinates)
        else:
            raise ValueError(f"Unsupported building geometry: {kind}")
    canonical(data)
    return data


def building_rows(db, source_run, observed_at):
    from .public_data import timestamp

    for row in db.execute(
        "SELECT * FROM observations WHERE run_id=? AND source='buildings' "
        "AND kind='buildings' ORDER BY entity_id",
        (source_run,),
    ):
        data = validate_building(json.loads(row["payload_json"]))
        yield {
            "run_id": source_run,
            "observed_at": timestamp(observed_at),
            "source_observed_at": timestamp(row["observed_at"]),
            "source_url": row["source_url"],
            "content_hash": row["content_hash"],
            "building_uid": f"uw-map:{data['map_object_id']}",
            **{
                key: data.get(key)
                for key in (
                    "map_object_id",
                    "building_number",
                    "object_type",
                    "name",
                    "street_address",
                    "description",
                    "hours",
                )
            },
            "longitude": data["lnglat"][0],
            "latitude": data["lnglat"][1],
            "geometry_json": canonical(data["geojson"])
            if data.get("geojson")
            else None,
            "meta_json": canonical(data.get("meta") or {}),
        }
