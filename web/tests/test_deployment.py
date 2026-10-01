import json
from pathlib import Path
import subprocess
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from uwcourses_site.deployment import (
    PublishedDatabase,
    Release,
    deploy,
    database_matches,
    verify_database,
    worker_state,
    current_commit,
    import_part,
    published_database,
    restore_readiness,
    wrangler,
)


class DeploymentTests(unittest.TestCase):
    release = Release("a" * 40, "b" * 64, 10)

    def report(self, **changes):
        status = {
            "revision": self.release.revision,
            "projection_id": self.release.projection,
            "courses": self.release.courses,
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
                            "serving": "d" * 32,
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
        previous=None,
        failed_part=1,
        recovery_error=False,
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
                if (
                    failure in {"import", "cancel"}
                    and "--file" in args
                    and args[-1].endswith(f"000{failed_part}.sql")
                ):
                    raise subprocess.CalledProcessError(
                        1,
                        ["wrangler"],
                        stderr="Cancelled due to no poll() received in 15000ms."
                        if failure == "cancel"
                        else "Invalid SQL",
                    )
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
                patch("uwcourses_site.deployment.time.sleep"),
                patch(
                    "uwcourses_site.deployment.published_database",
                    return_value=previous,
                ),
                patch(
                    "uwcourses_site.deployment.restore_readiness",
                    side_effect=RuntimeError("D1 unavailable")
                    if recovery_error
                    else None,
                ) as restore,
                patch(
                    "uwcourses_site.deployment.database_report",
                    return_value=self.report(courses=0)
                    if failure == "verify"
                    else self.report(),
                ),
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
                    ) as caught:
                        deploy(config, root, first=first)
                    if failure == "cancel":
                        self.assertIsInstance(
                            caught.exception, subprocess.CalledProcessError
                        )
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
                if (
                    failure == "cancel"
                    and failed_part == 1
                    and previous
                    and not changed
                ):
                    restore.assert_called_once_with(config, previous)
                else:
                    restore.assert_not_called()

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

    @patch("uwcourses_site.deployment.time.sleep")
    @patch("uwcourses_site.deployment.wrangler")
    def test_cancelled_file_is_retried_without_restarting_prior_files(
        self, command, sleep
    ):
        cancelled = subprocess.CalledProcessError(
            1, ["wrangler"], output="Cancelled due to no poll() received in 15000ms."
        )
        command.side_effect = [cancelled, cancelled, ""]
        config, part = Path("wrangler.json"), Path("0002.sql")
        import_part(config, part)
        self.assertEqual(command.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5])
        self.assertTrue(
            all(call.args[-1] == str(part) for call in command.call_args_list)
        )

    @patch("uwcourses_site.deployment.time.sleep")
    @patch("uwcourses_site.deployment.wrangler")
    def test_unconfirmed_failures_are_not_replayed(self, command, sleep):
        for message in ("Invalid SQL", "HTTP 403", "Network timeout"):
            with self.subTest(message=message):
                command.reset_mock()
                command.side_effect = subprocess.CalledProcessError(
                    1, ["wrangler"], stderr=message
                )
                with self.assertRaises(subprocess.CalledProcessError):
                    import_part(Path("wrangler.json"), Path("0001.sql"))
                command.assert_called_once()
                sleep.assert_not_called()

    @patch("uwcourses_site.deployment.time.sleep")
    @patch("uwcourses_site.deployment.wrangler")
    def test_import_cancellation_retries_are_bounded(self, command, sleep):
        command.side_effect = subprocess.CalledProcessError(
            1, ["wrangler"], stderr="Cancelled due to no poll() received in 15000ms."
        )
        with self.assertRaises(subprocess.CalledProcessError):
            import_part(Path("wrangler.json"), Path("0001.sql"))
        self.assertEqual(command.call_count, 4)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 5, 10])

    def test_exhausted_first_file_cancellation_recovers_previous_search(self):
        previous = PublishedDatabase.read(self.report())
        self.run_deploy(failure="cancel", previous=previous)

    def test_recovery_failure_preserves_the_original_import_error(self):
        self.run_deploy(
            failure="cancel",
            previous=PublishedDatabase.read(self.report()),
            recovery_error=True,
        )

    def test_partial_import_or_changed_worker_cannot_restore_old_readiness(self):
        previous = PublishedDatabase.read(self.report())
        self.run_deploy(failure="cancel", previous=previous, failed_part=2)
        self.run_deploy(failure="cancel", previous=previous, changed=True)
        self.run_deploy(failure="import", previous=previous)

    @patch("uwcourses_site.deployment.database_report")
    def test_recovery_snapshot_must_match_the_live_worker_and_binding(self, report):
        report.return_value = self.report(ready="false")
        with TemporaryDirectory() as directory:
            config = Path(directory) / "wrangler.json"
            config.write_text(json.dumps({"d1_databases": [{"database_id": "single"}]}))
            state = {"DB": "single", "DATA_PROJECTION": self.release.projection}
            self.assertEqual(
                published_database(config, state), PublishedDatabase.read(self.report())
            )
            for change in ({"DB": "other"}, {"DATA_PROJECTION": "e" * 64}):
                self.assertIsNone(published_database(config, {**state, **change}))
            report.return_value = self.report(courses=9)
            self.assertIsNone(published_database(config, state))

    @patch("uwcourses_site.deployment.wrangler")
    @patch("uwcourses_site.deployment.database_report")
    def test_readiness_restoration_checks_identity_before_and_after_write(
        self, report, command
    ):
        previous = PublishedDatabase.read(self.report())
        report.side_effect = [self.report(ready="false"), self.report()]
        restore_readiness(Path("wrangler.json"), previous)
        sql = command.call_args.args[-1]
        self.assertIn("key='ready' AND value='false'", sql)
        self.assertIn("key='status'", sql)
        self.assertIn("key='serving'", sql)
        self.assertIn("count(*) FROM courses)=10", sql)
        command.reset_mock()
        report.side_effect = [self.report(serving="e" * 32)]
        with self.assertRaisesRegex(ValueError, "changed"):
            restore_readiness(Path("wrangler.json"), previous)
        command.assert_not_called()
        report.side_effect = [self.report(ready="false"), self.report(ready="false")]
        with self.assertRaisesRegex(ValueError, "could not be restored"):
            restore_readiness(Path("wrangler.json"), previous)

    @patch("uwcourses_site.deployment.subprocess.run")
    def test_wrangler_preserves_failure_output_for_cancellation_detection(self, run):
        failure = subprocess.CalledProcessError(
            1,
            ["wrangler"],
            output="Starting import",
            stderr="Cancelled due to no poll() received",
        )
        run.side_effect = failure
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            wrangler(Path("wrangler.json"), "d1", "execute")
        self.assertIs(caught.exception, failure)
        self.assertIs(run.call_args.kwargs["stdout"], subprocess.PIPE)
        self.assertIs(run.call_args.kwargs["stderr"], subprocess.PIPE)

    def test_recovery_sql_rejects_changes_between_verification_and_update(self):
        for change in (None, "status", "serving", "courses"):
            with self.subTest(change=change), sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.executescript(
                    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);"
                    "CREATE TABLE courses(uid TEXT PRIMARY KEY);"
                )
                row = json.loads(self.report(ready="false"))[0]["results"][0]
                status = json.loads(row["status"])
                status["label"] = "O'Brien"
                row["status"] = json.dumps(status)
                db.executemany(
                    "INSERT INTO metadata VALUES(?,?)",
                    [(key, row[key]) for key in ("ready", "status", "serving")],
                )
                db.executemany(
                    "INSERT INTO courses VALUES(?)", [(str(i),) for i in range(10)]
                )
                snapshot = PublishedDatabase(row["status"], 10, row["serving"])

                def report(config):
                    values = dict(db.execute("SELECT key,value FROM metadata"))
                    values["courses"] = db.execute(
                        "SELECT count(*) FROM courses"
                    ).fetchone()[0]
                    return json.dumps([{"success": True, "results": [values]}])

                def command(config, *args):
                    if change == "courses":
                        db.execute("INSERT INTO courses VALUES('new')")
                    elif change:
                        db.execute(
                            "UPDATE metadata SET value='changed' WHERE key=?", [change]
                        )
                    db.execute(args[-1])

                with (
                    patch(
                        "uwcourses_site.deployment.database_report", side_effect=report
                    ),
                    patch("uwcourses_site.deployment.wrangler", side_effect=command),
                ):
                    if change:
                        with self.assertRaises(ValueError):
                            restore_readiness(Path("wrangler.json"), snapshot)
                    else:
                        restore_readiness(Path("wrangler.json"), snapshot)
                ready = db.execute(
                    "SELECT value FROM metadata WHERE key='ready'"
                ).fetchone()[0]
                self.assertEqual(ready, "false" if change else "true")

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
