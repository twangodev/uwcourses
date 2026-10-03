import copy
import json
from pathlib import Path
import tempfile
import unittest

from scrapy.http import Response, Request

from uwcourses.buildings import validate_building
from uwcourses.spiders import BuildingSpider
from uwcourses.store import Store

FIXTURE = Path(__file__).parent / "fixtures/campus-building.json"


def response(url, body):
    return Response(url, body=body.encode(), request=Request(url))


class BuildingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.run = self.store.new_run("1272", {})
        self.spider = BuildingSpider(store=self.store, run=self.run)
        self.data = json.loads(FIXTURE.read_text())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_directory_uses_fpm_id_and_skips_unidentified_groups(self):
        html = """<table>
            <tr><th>Name</th><th>FP&amp;M Building Number</th></tr>
            <tr><td><a href="/?initObj=0155">Computer Sciences</a></td><td>0155</td></tr>
            <tr><td><a href="/">Eagle Heights</a></td><td></td></tr>
            <tr><td><a href="/?initObj=0155">Duplicate</a></td><td>0155</td></tr>
        </table>"""
        requests = list(
            self.spider.directory(response("https://map.wisc.edu/buildings/", html))
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url, "https://map.wisc.edu/?initObj=0155")
        self.assertEqual(requests[0].cb_kwargs, {"number": "0155"})
        for bad in (
            "<table></table>",
            html.replace("/?initObj=0155", "https://example.com/?initObj=0155"),
        ):
            with self.assertRaises(ValueError):
                list(
                    self.spider.directory(
                        response("https://map.wisc.edu/buildings/", bad)
                    )
                )

    def test_embedded_record_preserves_source_identity_geometry_and_metadata(self):
        html = (
            "window.Rails="
            + json.dumps({"init_obj": self.data})
            + ";window.W=window.Rails;"
        )
        url = "https://map.wisc.edu/?initObj=0155"
        (record,) = self.spider.building(response(url, html), "0155")
        self.store.put(self.run, "buildings", record)
        self.assertEqual(record["key"], "366")
        self.assertEqual(record["source_url"], url)
        self.assertEqual(self.store.records(self.run, "buildings")["366"], self.data)
        with self.assertRaises(ValueError):
            list(self.spider.building(response(url, html), "0050"))
        with self.assertRaises(ValueError):
            list(
                self.spider.building(
                    response(url, 'window.Rails={"init_obj":false};window.W='), "0155"
                )
            )

    def test_holes_multipolygons_and_missing_geometry_are_preserved(self):
        validate_building({**self.data, "object_type": "building_partial"})
        rings = self.data["geojson"]["coordinates"]
        for geometry in (
            None,
            {"type": "Point", "coordinates": self.data["lnglat"]},
            {"type": "MultiPolygon", "coordinates": [rings, rings]},
            {"type": "Polygon", "coordinates": rings + rings},
        ):
            data = {**self.data, "geojson": geometry}
            self.assertEqual(validate_building(data), data)

    def test_invalid_identity_and_geometry_cannot_enter_store(self):
        for patch in (
            {"map_object_id": 155},
            {"building_number": 155},
            {"lnglat": [43, -189]},
            {"lnglat": [True, 43]},
            {"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [1, 1]]]}},
        ):
            data = {**copy.deepcopy(self.data), **patch}
            with self.assertRaises(ValueError):
                self.store.put(
                    self.run,
                    "buildings",
                    {
                        "kind": "buildings",
                        "key": "366",
                        "payload": data,
                        "source_url": "https://map.wisc.edu/?initObj=0155",
                    },
                )
        self.assertEqual(self.store.records(self.run, "buildings"), {})
