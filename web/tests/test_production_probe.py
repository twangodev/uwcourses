import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import requests

from uwcourses_site.production_probe import production_probe


class ProductionProbeTests(unittest.TestCase):
    def exercise(self, failure=None):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "wrangler.json"
            config.write_text(
                json.dumps(
                    {
                        "name": "uwcourses",
                        "compatibility_date": "2026-09-08",
                    }
                )
            )
            calls = []
            probe_config = None

            def command(path, *args, **kwargs):
                nonlocal probe_config
                probe_config = path
                settings = json.loads(path.read_text())
                self.assertTrue(settings["name"].startswith("uwcourses-search-probe-"))
                self.assertEqual(
                    settings["services"],
                    [
                        {"binding": "PRODUCTION", "service": "uwcourses"},
                    ],
                )
                self.assertNotIn("d1_databases", settings)
                calls.append(args)
                if args[0] == "deploy":
                    if failure == "deploy":
                        raise RuntimeError("Deployment failed")
                    return "Deployed https://probe.example.workers.dev"
                self.assertEqual(args, ("delete", "--force"))
                return "Deleted"

            with (
                patch("uwcourses_site.production_probe.wrangler", side_effect=command),
                patch("uwcourses_site.production_probe.probe_json", return_value={}),
            ):

                def check():
                    with production_probe(config, "https://uwcourses.com") as (
                        base,
                        headers,
                    ):
                        self.assertEqual(base, "https://probe.example.workers.dev")
                        settings = json.loads(probe_config.read_text())
                        self.assertEqual(
                            headers["X-Search-Probe"], settings["vars"]["PROBE_TOKEN"]
                        )
                        self.assertEqual(
                            settings["vars"]["TARGET_ORIGIN"], "https://uwcourses.com"
                        )
                        if failure == "check":
                            raise RuntimeError("Verification failed")

                if failure:
                    with self.assertRaises(RuntimeError):
                        check()
                else:
                    check()
            self.assertEqual(calls, [("deploy",), ("delete", "--force")])
            self.assertFalse(probe_config.exists())

    def test_routes_to_active_production_worker_and_removes_credentials(self):
        self.exercise()

    def test_cleanup_runs_after_failed_verification(self):
        self.exercise("check")

    def test_cleanup_runs_after_an_ambiguous_probe_deployment_error(self):
        self.exercise("deploy")

    @patch("uwcourses_site.production_probe.time.sleep")
    def test_waits_for_workers_dev_route_propagation_before_yielding(self, sleep):
        with TemporaryDirectory() as directory:
            config = Path(directory) / "wrangler.json"
            config.write_text(
                json.dumps({"name": "uwcourses", "compatibility_date": "2026-09-08"})
            )
            with (
                patch(
                    "uwcourses_site.production_probe.wrangler",
                    side_effect=[
                        "Deployed https://probe.example.workers.dev",
                        "Deleted",
                    ],
                ) as command,
                patch(
                    "uwcourses_site.production_probe.probe_json",
                    side_effect=[
                        requests.HTTPError("1042 no script"),
                        {},
                    ],
                ) as read,
            ):
                with production_probe(config, "https://uwcourses.com"):
                    self.assertEqual(read.call_count, 2)
                self.assertEqual(command.call_count, 2)
                sleep.assert_called_once_with(5)
