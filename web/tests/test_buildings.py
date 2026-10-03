import json
import hashlib
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

from uwcourses_site.importer import building_footprints, verify


class BuildingProjectionTests(unittest.TestCase):
    def test_optional_table_is_verified_and_old_releases_are_supported(self):
        expected = json.loads(
            (Path(__file__).parents[1] / "uwcourses_site/schema-v6.json").read_text()
        )
        types = {
            "string": pa.string(),
            "int64": pa.int64(),
            "double": pa.float64(),
            "bool": pa.bool_(),
            "list<item: string>": pa.list_(pa.string()),
            "timestamp[us, tz=UTC]": pa.timestamp("us", tz="UTC"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            (source / "public").mkdir()
            schema = {"version": 6, "tables": {}}
            manifest = {"files": {}}
            for name, table in expected["tables"].items():
                if name == "buildings_current":
                    continue
                path = source / "public" / f"{name}.parquet"
                arrow = pa.schema(
                    [(key, types[typ]) for key, typ in table["columns"].items()]
                )
                pq.write_table(pa.Table.from_pylist([], schema=arrow), path)
                schema["tables"][name] = {"rows": 0}
                manifest["files"][f"public/{name}.parquet"] = {
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            def save():
                (source / "public/schema.json").write_text(json.dumps(schema))
                (source / "manifest.json").write_text(json.dumps(manifest))

            save()
            verify(source)
            name = "buildings_current"
            path = source / "public/buildings_current.parquet"
            arrow = pa.schema(
                [
                    (key, types[typ])
                    for key, typ in expected["tables"][name]["columns"].items()
                ]
            )
            pq.write_table(pa.Table.from_pylist([], schema=arrow), path)
            with self.assertRaisesRegex(ValueError, "Undeclared"):
                verify(source)
            schema["tables"][name] = {"rows": 0}
            manifest["files"][f"public/{name}.parquet"] = {
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            save()
            verify(source)
            manifest["files"][f"public/{name}.parquet"]["sha256"] = "0" * 64
            save()
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                verify(source)

    def test_projects_all_parts_and_holes_with_source_aliases(self):
        outer = [[-89.41, 43.07], [-89.40, 43.07], [-89.40, 43.08], [-89.41, 43.07]]
        holes = [outer, outer]
        data = {
            "building_uid": "uw-map:366",
            "name": "Computer Sciences",
            "building_number": "0155",
            "source_url": "https://map.wisc.edu/?initObj=0155",
            "geometry_json": json.dumps(
                {"type": "MultiPolygon", "coordinates": [holes, [outer]]}
            ),
            "meta_json": json.dumps(
                {"cname": "Computer Sciences and Statistics", "sname": "bdg_CmpSc"}
            ),
        }
        projected = building_footprints([data])
        (building,) = projected["buildings"]
        self.assertEqual(building["id"], "uw-map:366")
        self.assertEqual(building["buildingNumber"], "0155")
        self.assertEqual(
            building["names"], ["Computer Sciences", "Computer Sciences and Statistics"]
        )
        self.assertEqual(len(building["polygons"]), 2)
        self.assertEqual(len(building["polygons"][0]), 2)
        self.assertEqual(building["points"], building["polygons"][0][0])
        self.assertEqual(building["points"][0], [397.06, 432.86])
        self.assertEqual(building_footprints([])["buildings"], [])
        self.assertEqual(
            building_footprints([{**data, "geometry_json": None}])["buildings"], []
        )
