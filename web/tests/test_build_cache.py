import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import requests

from uwcourses_site import build_cache as cache


class BuildCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.plan = self.root / "plan.json"
        self.stage = self.root / "import"
        self.stage.mkdir()
        self.revision = "a" * 40
        self.plan.write_text(
            json.dumps({"revision": self.revision, "keys": {"import": "key"}})
        )
        self.status = self.stage / "status.json"
        self.status.write_text(
            json.dumps({"revision": self.revision, "limited": False})
        )
        for target, value in [("PLAN", self.plan), ("STAGES", {"import": self.stage})]:
            patcher = patch.object(cache, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_manifest_rejects_missing_corrupt_extra_and_wrong_revision(self):
        self.assertFalse(cache.valid("import"))
        cache.seal("import")
        self.assertTrue(cache.valid("import"))
        extra = self.stage / "unexpected"
        extra.write_text("extra")
        self.assertFalse(cache.valid("import"))
        extra.unlink()
        original = self.status.read_text()
        self.status.write_text(original + " ")
        self.assertFalse(cache.valid("import"))
        self.status.write_text(original)
        self.plan.write_text(
            json.dumps({"revision": "b" * 40, "keys": {"import": "key"}})
        )
        self.assertFalse(cache.valid("import"))
        with self.assertRaises(ValueError):
            cache.seal("import")
        self.status.unlink()
        self.assertFalse(cache.valid("import"))

    def test_input_boundaries(self):
        files = {
            "web/uwcourses_site/importer.py": "importer",
            "src/lib/server/data.ts": "documents",
            "web/social-card.html": "social",
            "web/tests/browser/setup.ts": "browser",
            "src/routes/+page.svelte": "ui",
        }
        for name, content in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        before = cache.keys(self.revision, self.root)
        expected = {
            "importer": {"import", "documents", "social", "browser"},
            "documents": {"documents", "social"},
            "social": {"social"},
            "browser": {"browser"},
            "ui": set(),
        }
        for name, content in files.items():
            path = self.root / name
            path.write_text(content + "changed")
            after = cache.keys(self.revision, self.root)
            self.assertEqual(
                {stage for stage in before if before[stage] != after[stage]},
                expected[content],
            )
            path.write_text(content)
        after = cache.keys("b" * 40, self.root)
        self.assertTrue(all(before[k] != after[k] for k in before))

    @patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"})
    @patch.object(cache, "outputs")
    @patch.object(cache, "keys", return_value={})
    @patch.object(cache.subprocess, "check_output", return_value="commit\n")
    @patch.object(cache.requests, "get")
    def test_nightly_skips_only_identical_healthy_release(
        self, get, commit, keys, outputs
    ):
        for deployed, changed in [
            ({"revision": self.revision, "site_commit": "commit"}, False),
            ({"revision": "b" * 40, "site_commit": "commit"}, True),
            ({"revision": self.revision, "site_commit": "older"}, True),
            ({}, True),
            ([], True),
        ]:

            def response(url, **kwargs):
                get.return_value.json.return_value = (
                    {"revision": self.revision, "items": [{"course_uid": "course"}]}
                    if url.endswith("/api/suggest")
                    else deployed
                )
                return get.return_value

            get.side_effect = response
            cache.resolve(self.revision)
            self.assertEqual(outputs.call_args.args[0]["changed"], changed)
        get.side_effect = requests.ConnectionError()
        cache.resolve(self.revision)
        self.assertTrue(outputs.call_args.args[0]["changed"])

    @patch.dict(os.environ, {"GITHUB_EVENT_NAME": "schedule"})
    @patch.object(cache, "outputs")
    @patch.object(cache, "keys", return_value={})
    @patch.object(cache.subprocess, "check_output", return_value="commit\n")
    @patch.object(cache.requests, "get")
    def test_identical_metadata_cannot_hide_unavailable_search(
        self, get, commit, keys, outputs
    ):
        for result in (
            requests.HTTPError("503 updating"),
            {"revision": self.revision, "items": []},
            {"revision": "old", "items": [{"course_uid": "course"}]},
            [],
        ):
            with self.subTest(result=result):

                def response(url, **kwargs):
                    if url.endswith("/api/suggest"):
                        if isinstance(result, Exception):
                            raise result
                        data = result
                    else:
                        data = {"revision": self.revision, "site_commit": "commit"}
                    get.return_value.json.return_value = data
                    return get.return_value

                get.side_effect = response
                cache.resolve(self.revision)
                self.assertTrue(outputs.call_args.args[0]["changed"])

    @patch("huggingface_hub.HfApi")
    def test_hf_failure_never_falls_back_to_cached_data(self, api):
        api.return_value.dataset_info.side_effect = RuntimeError("HF unavailable")
        with self.assertRaises(RuntimeError):
            cache.resolve()
        with self.assertRaises(ValueError):
            cache.resolve("main")
