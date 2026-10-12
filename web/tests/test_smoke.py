import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests

from uwcourses_site.deployment import Release
from uwcourses_site.smoke import probe_json, smoke_check


class SmokeTests(unittest.TestCase):
    release = Release("a" * 40, "b" * 64, 10)
    commit = "c" * 40

    def response(self, url, **kwargs):
        path = urlparse(url).path
        data = {"revision": self.release.revision}
        if path == "/api/status":
            data.update(site_commit=self.commit, projection_id=self.release.projection)
        elif path == "/api/facets":
            data["distributions"] = {"gpa": {"total": 10}}
        else:
            data["items"] = [{"course_uid": "course"}]
        response = Mock()
        response.json.return_value = data
        return response

    @patch("uwcourses_site.smoke.requests.get")
    def test_cloudflare_rejections_include_diagnostic_body_and_ray(self, get):
        response = requests.Response()
        response.status_code = 403
        response.url = "https://example.test/api/status"
        response._content = b"error code: 1010\n"
        response.headers["CF-Ray"] = "example-ray"
        get.return_value = response
        with self.assertRaisesRegex(requests.HTTPError, "example-ray.*1010"):
            probe_json(response.url)

    @patch("uwcourses_site.smoke.requests.get")
    def test_checks_release_and_all_search_surfaces(self, get):
        get.side_effect = self.response
        smoke_check("https://example.test", self.release, self.commit)
        self.assertEqual(get.call_count, 5)
        self.assertEqual(
            [urlparse(call.args[0]).path for call in get.call_args_list],
            [
                "/api/status",
                "/api/search",
                "/api/search",
                "/api/suggest",
                "/api/facets",
            ],
        )
        self.assertEqual(
            parse_qs(urlparse(get.call_args_list[2].args[0]).query)["kind"],
            ["instructor"],
        )
        for call in get.call_args_list:
            self.assertEqual(
                parse_qs(urlparse(call.args[0]).query)["revision"],
                [self.release.revision],
            )

    @patch("uwcourses_site.smoke.time.sleep")
    @patch("uwcourses_site.smoke.requests.get")
    def test_retries_temporary_unavailability_with_a_new_cache_key(self, get, sleep):
        first = True

        def response(url, **kwargs):
            nonlocal first
            if first:
                first = False
                raise requests.HTTPError("503 updating")
            return self.response(url, **kwargs)

        get.side_effect = response
        smoke_check("https://example.test", self.release, self.commit)
        sleep.assert_called_once_with(5)
        self.assertEqual(get.call_count, 6)
        self.assertNotEqual(
            get.call_args_list[0].args[0], get.call_args_list[1].args[0]
        )

    @patch("uwcourses_site.smoke.time.sleep")
    @patch("uwcourses_site.smoke.requests.get")
    def test_persistent_failure_or_wrong_release_fails_the_deployment_check(
        self, get, sleep
    ):
        for change in (
            {"revision": "old"},
            {"site_commit": "old"},
            {"projection_id": "old"},
            {"items": []},
            {"distributions": {}},
        ):
            with self.subTest(change=change):

                def response(url, **kwargs):
                    result = self.response(url, **kwargs)
                    result.json.return_value.update(change)
                    return result

                get.side_effect = response
                sleep.reset_mock()
                with self.assertRaises(ValueError):
                    smoke_check("https://example.test", self.release, self.commit)
                self.assertEqual(sleep.call_count, 5)
        get.side_effect = requests.HTTPError("503 updating")
        get.reset_mock()
        with self.assertRaises(requests.HTTPError):
            smoke_check("https://example.test", self.release, self.commit)
        self.assertEqual(get.call_count, 6)
