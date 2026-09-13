import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from uwcourses_site.deployment import (
    Release,
    deploy,
    database_matches,
    verify_database,
    worker_state,
    current_commit,
)


class DeploymentTests(unittest.TestCase):
    release = Release("a" * 40, "b" * 64, 10)

    def report(self, **changes):
        status = {
            "revision": self.release.revision,
            "projection_id": self.release.projection,
        }
        return json.dumps(
            [
                {
                    "success": True,
                    "results": [
                        {
                            "ready": "true",
                            "courses": 10,
                            "status": json.dumps(status),
                            **changes,
                        }
                    ],
                }
            ]
        )

    def test_staged_database_must_match(self):
        verify_database(self.report(), self.release)
        for changes in ({"ready": "false"}, {"courses": 9}, {"status": "{}"}):
            with self.assertRaises(ValueError):
                verify_database(self.report(**changes), self.release)

    def run_deploy(
        self,
        failure=None,
        changed=False,
        reuse=False,
        missing=False,
        first=False,
        stale=False,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sql").mkdir()
            for name in ("0001.sql", "0002.sql"):
                (root / "sql" / name).write_text("SELECT 1;")
            (root / "status.json").write_text(
                json.dumps(
                    {
                        "limited": False,
                        "revision": self.release.revision,
                        "projection_id": self.release.projection,
                        "courses": 10,
                    }
                )
            )
            config = root / "wrangler.json"
            config.write_text(
                json.dumps(
                    {
                        "name": "uwcourses",
                        "d1_databases": [
                            {"binding": "DB", "database_id": "single"},
                        ],
                    }
                )
            )
            initial = None if missing else {"DB": "single", "DATA_PROJECTION": "old"}
            states = [initial, {"DB": "changed"} if changed else initial]
            calls = []
            github_output = root / "github-output"

            def command(config, *args, **kwargs):
                calls.append(args)
                if failure == "import" and "--file" in args:
                    raise subprocess.CalledProcessError(1, ["wrangler"])
                return self.report(courses=0) if failure == "verify" else self.report()

            with (
                patch.dict(
                    "os.environ",
                    {
                        "CLOUDFLARE_ACCOUNT_ID": "a" * 32,
                        "CLOUDFLARE_API_TOKEN": "test",
                        "GITHUB_OUTPUT": str(github_output),
                    },
                ),
                patch(
                    "uwcourses_site.deployment.current_commit", return_value=not stale
                ),
                patch(
                    "uwcourses_site.deployment.worker_state", side_effect=states
                ) as state,
                patch("uwcourses_site.deployment.wrangler", side_effect=command),
                patch("uwcourses_site.deployment.database_matches", return_value=reuse),
                patch("uwcourses_site.deployment.subprocess.run") as run,
            ):
                run.return_value.stdout = "c" * 40
                if stale:
                    deploy(config, root, first=first)
                    self.assertEqual(calls, [])
                    state.assert_not_called()
                    self.assertFalse(github_output.exists())
                elif failure or changed or (missing and not first):
                    with self.assertRaises(
                        (ValueError, RuntimeError, subprocess.CalledProcessError)
                    ):
                        deploy(config, root, first=first)
                    self.assertFalse(any(call[0] == "deploy" for call in calls))
                    self.assertFalse(github_output.exists())
                    self.assertFalse(
                        any("VALUES('serving'" in str(call[-1]) for call in calls)
                    )
                else:
                    deploy(config, root, first=first)
                    self.assertEqual(calls[-1][0], "deploy")
                    self.assertEqual(github_output.read_text(), "deployed=true\n")
                    self.assertIn("VALUES('serving'", calls[-2][-1])
                    imports = [call for call in calls if "--file" in call]
                    self.assertEqual(len(imports), 0 if reuse else 2)
                    if imports:
                        self.assertTrue(all(call[2] == "DB" for call in imports))
                        self.assertIn("VALUES('ready','false')", calls[0][-1])
                        self.assertLess(calls.index(calls[0]), calls.index(imports[0]))
                        self.assertTrue(imports[0][-1].endswith("0001.sql"))

    def test_first_deployment_is_explicit(self):
        self.run_deploy(missing=True)
        self.run_deploy(missing=True, first=True)

    def test_readiness_queries_capture_json_from_the_subprocess(self):
        for tables in (0, 2):
            with self.subTest(tables=tables):
                outputs = iter(
                    [
                        json.dumps(
                            [{"results": [{"tables": tables}], "success": True}]
                        ),
                        self.report(),
                    ]
                )

                def run(args, **kwargs):
                    self.assertIn("--json", args)
                    self.assertIs(kwargs.get("stdout"), subprocess.PIPE)
                    return subprocess.CompletedProcess(args, 0, stdout=next(outputs))

                with patch(
                    "uwcourses_site.deployment.subprocess.run", side_effect=run
                ) as command:
                    self.assertEqual(
                        database_matches(Path("wrangler.json"), self.release),
                        tables == 2,
                    )
                    self.assertEqual(command.call_count, 1 if tables == 0 else 2)

    @patch("uwcourses_site.deployment.wrangler")
    def test_database_readiness_controls_reuse_after_failed_publication(self, command):
        tables = json.dumps([{"results": [{"tables": 2}], "success": True}])
        for report, expected in [
            (self.report(), True),
            (self.report(ready="false"), False),
            (self.report(status="{}"), False),
        ]:
            command.side_effect = [tables, report]
            self.assertEqual(
                database_matches(Path("wrangler.json"), self.release), expected
            )
        command.side_effect = [
            json.dumps([{"results": [{"tables": 0}], "success": True}])
        ]
        self.assertFalse(database_matches(Path("wrangler.json"), self.release))

    def test_import_verify_and_publish_order(self):
        self.run_deploy()

    def test_reuse_still_verifies_before_publish(self):
        self.run_deploy(reuse=True)

    def test_import_failure_stops_publish(self):
        self.run_deploy(failure="import")

    def test_verification_failure_stops_publish(self):
        self.run_deploy(failure="verify")

    def test_concurrent_change_stops_publish(self):
        self.run_deploy(changed=True)

    def test_incomplete_release_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps({"limited": True}))
            with self.assertRaises(ValueError):
                Release.read(path)

    @patch("uwcourses_site.deployment.requests.get")
    def test_only_404_means_missing_worker(self, get):
        get.return_value.status_code = 404
        self.assertIsNone(worker_state("account", "token", "worker"))
        get.return_value.status_code = 403
        get.return_value.raise_for_status.side_effect = RuntimeError("Forbidden")
        with self.assertRaises(RuntimeError):
            worker_state("account", "token", "worker")

    def test_superseded_build_cannot_touch_production(self):
        self.run_deploy(stale=True)

    @patch.dict(
        "os.environ",
        {"GITHUB_REPOSITORY": "twangodev/uwcourses", "GITHUB_TOKEN": "test"},
    )
    @patch("uwcourses_site.deployment.requests.get")
    def test_main_guard_fails_closed(self, get):
        get.return_value.json.return_value = {"sha": "new"}
        self.assertFalse(current_commit("old"))
        self.assertTrue(current_commit("new"))
        get.return_value.raise_for_status.side_effect = RuntimeError(
            "GitHub unavailable"
        )
        with self.assertRaises(RuntimeError):
            current_commit("new")
