"""Command-line entry point; each crawl runs in its own Scrapy process."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .models import canonical
from sqlalchemy import select, update, literal
from sqlalchemy.dialects.sqlite import insert

from .schema import runs, stages, responses
from .store import SOURCES, Store


def parser():
    root = argparse.ArgumentParser(prog="uwcourses")
    root.add_argument(
        "--workspace",
        type=Path,
        default=Path(
            os.environ.get(
                "UWCOURSES_WORKSPACE",
                os.environ.get("COURSEMAP_WORKSPACE", "./.coursemap"),
            )
        ),
    )
    commands = root.add_subparsers(
        dest="command",
        required=True,
    )
    run = commands.add_parser(
        "scrape",
        aliases=["run"],
        help="Create an immutable source snapshot; no model inference",
    )
    run.add_argument(
        "--semester", required=True, help="UW numeric term code, e.g. 1272"
    )
    run.add_argument("--concurrency", type=int, default=32)
    run.add_argument("--per-domain", type=int, default=16)
    run.add_argument("--target-concurrency", type=float, default=8)
    run.add_argument("--download-delay", type=float, default=0.1)
    run.add_argument(
        "--include-instructors",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    for name in ("enrich", "release"):
        command = commands.add_parser(name)
        command.add_argument("run_id")
        if name == "enrich":
            command.add_argument("--models-config", type=Path, required=True)
        if name == "enrich":
            command.add_argument("--prepare-only", action="store_true")
            command.add_argument("--reuse-job", action="append", default=[])
            command.add_argument(
                "--allow-partial-reuse",
                action="store_true",
                help="Snapshot completed student-summary results from unfinished reuse jobs",
            )
            command.add_argument("--profile", default="enrichment")
            command.add_argument("--task", type=Path, required=True)
            command.add_argument(
                "--course",
                action="append",
                help="Explicit course ID or alias; repeat for a targeted test",
            )
            command.add_argument(
                "--limit",
                type=int,
                default=100,
                help="Stable sample size; 0 processes all courses",
            )
        if name == "release":
            command.add_argument("--enrichment", action="append", default=[])
    for name in ("enrich-resume", "job-status", "job-report"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
        if name == "enrich-resume":
            command.add_argument("--concurrency", type=int)
            command.add_argument("--request-timeout-seconds", type=int)
    repair = commands.add_parser(
        "enrich-repair",
        help="Repair saved rejected sections through validator conversation turns",
    )
    repair.add_argument("job_id")
    repair.add_argument("--models-config", type=Path, required=True)
    repair.add_argument("--profile", default="enrichment-unified")
    repair.add_argument("--limit", type=int, default=20)
    repair.add_argument("--course", action="append")
    repair.add_argument("--turns", type=int, default=3)
    repair.add_argument("--prepare-only", action="store_true")
    repair.add_argument(
        "--task", type=Path, help="Updated repair prompt with the same output schema"
    )
    descriptions = {
        "resume": "Continue an interrupted run",
        "status": "Show source and stage completion",
        "validate": "Check source completeness and relationships",
        "publish": "Upload a completed release to Hugging Face",
        "replay": "Create a new run from archived source responses",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description)
        command.add_argument("run_id")
        if name == "publish":
            command.add_argument("--repo", required=True, help="HF dataset owner/name")
            command.add_argument(
                "--parquet-only",
                action="store_true",
                help="Publish tables, card and sync metadata without SQLite",
            )
        if name == "replay":
            command.add_argument("--source", choices=SOURCES, required=True)
    for name, description in (
        (
            "refresh-instructors",
            "Collect faculty/RMP data using an existing frozen catalog and grades",
        ),
        (
            "refresh-buildings",
            "Collect official campus buildings using an existing frozen course snapshot",
        ),
    ):
        refresh = commands.add_parser(name, help=description)
        refresh.add_argument("run_id")
        refresh.add_argument(
            "--source-workspace",
            type=Path,
            help="Optional separate source workspace; the new run is written to --workspace",
        )
    commands.add_parser(
        "public-export",
        help="Build public Parquet tables from a verified archive",
    ).add_argument("release_id")
    outcomes = commands.add_parser(
        "outcomes-refresh",
        help="Prepare an outcomes-only supplement without changing existing course data",
    )
    outcomes.add_argument("--publication", type=Path, required=True)
    outcomes.add_argument("--evidence-jsonl", type=Path, required=True)
    outcomes.add_argument("--evidence-manifest", type=Path, required=True)
    outcomes.add_argument("--parent-revision", required=True)
    outcomes.add_argument("--output", type=Path, required=True)
    outcomes.add_argument(
        "--fallback",
        type=Path,
        help="Verified matching archive for files absent from the local publication",
    )
    publish_outcomes = commands.add_parser(
        "outcomes-publish",
        help="Explicitly publish a reviewed outcomes supplement with a pinned parent guard",
    )
    publish_outcomes.add_argument("--candidate", type=Path, required=True)
    publish_outcomes.add_argument("--repo", required=True)
    publish_outcomes.add_argument("--parent-revision", required=True)
    traces = commands.add_parser(
        "traces-refresh",
        help="Prepare recorded role/content trace columns without inference",
    )
    traces.add_argument("--publication", type=Path, required=True)
    traces.add_argument("--parent-revision", required=True)
    traces.add_argument("--output", type=Path, required=True)
    publish_traces = commands.add_parser(
        "traces-publish",
        help="Publish a reviewed trace supplement with a pinned parent guard",
    )
    publish_traces.add_argument("--candidate", type=Path, required=True)
    publish_traces.add_argument("--repo", required=True)
    publish_traces.add_argument("--parent-revision", required=True)
    models = commands.add_parser("models-lock")
    models.add_argument("--models-config", type=Path, required=True)
    models.add_argument("--profile", action="append", required=True)
    models.add_argument("--output", type=Path, required=True)
    classify = commands.add_parser(
        "classifier-predict",
        help="Run pinned optional Laya inference on manually labeled evidence JSONL",
    )
    classify.add_argument("--input", type=Path, required=True)
    classify.add_argument("--output", type=Path, required=True)
    classify.add_argument("--revision", required=True)
    classify.add_argument("--device")
    evaluate = commands.add_parser(
        "classifier-evaluate",
        help="Evaluate supplied predictions without loading any model",
    )
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    crawl = commands.add_parser("_crawl")
    crawl.add_argument("run_id")
    crawl.add_argument("source", choices=SOURCES)
    crawl.add_argument("--offline", action="store_true")
    return root


def code_hash():
    import hashlib

    directory = Path(__file__).parent
    files = sorted(directory.glob("*.py")) + sorted(directory.parent.glob("*.py"))
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def execute_source(store, run, source, offline=False):
    store.stage(run, source, "running")
    command = [
        sys.executable,
        "-m",
        "uwcourses.cli",
        "--workspace",
        str(store.root),
        "_crawl",
        run,
        source,
    ]
    if offline:
        command.append("--offline")
    log = store.root / "runs" / run / f"{source}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as output:
        result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        store.stage(run, source, "failed", f"See {log.name}")
        raise RuntimeError(f"{source} failed; see {log}")
    store.stage(run, source, "complete")


def execute(store, run):
    try:
        return execute_run(store, run)
    except Exception:
        with store.db:
            store.db.execute(
                update(runs)
                .where(runs.c.run_id == run, runs.c.status != "complete")
                .values(status="failed"),
            )
        raise


def execute_run(store, run):
    from .lifecycle import scrape

    if json.loads(store.run(run)["config_json"]).get("workflow") != "snapshot-v1":
        if store.run(run)["status"] == "complete":
            return {"run_id": run, "status": "complete"}
        raise ValueError(
            "Legacy combined runs cannot resume; create a new scrape snapshot"
        )
    return scrape(store, run)


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "traces-refresh":
        from .traces_refresh import refresh_traces

        print(
            canonical(
                refresh_traces(args.publication, args.parent_revision, args.output)
            )
        )
        return
    if args.command == "traces-publish":
        from .traces_refresh import publish_traces

        print(
            canonical(publish_traces(args.candidate, args.repo, args.parent_revision))
        )
        return
    if args.command == "outcomes-refresh":
        from .outcomes_refresh import refresh_outcomes

        print(
            canonical(
                refresh_outcomes(
                    args.publication,
                    args.evidence_jsonl,
                    args.evidence_manifest,
                    args.parent_revision,
                    args.output,
                    args.fallback,
                )
            )
        )
        return
    if args.command == "outcomes-publish":
        from .outcomes_refresh import publish_outcomes

        print(
            canonical(publish_outcomes(args.candidate, args.repo, args.parent_revision))
        )
        return
    for name in ("run_id", "job_id"):
        value = getattr(args, name, None)
        if value and not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError(f"Invalid {name}")
    if args.command in {"classifier-predict", "classifier-evaluate"}:
        from .classification import evaluate, predict, read_jsonl, write_jsonl

        rows = read_jsonl(args.input)
        if args.command == "classifier-predict":
            write_jsonl(args.output, predict(rows, args.revision, args.device))
            print(canonical({"predictions": str(args.output), "decisions": len(rows)}))
        else:
            report = evaluate(rows)
            with args.output.open("x") as output:
                json.dump(report, output, indent=2, sort_keys=True, allow_nan=False)
            print(canonical(report))
        return
    if args.command == "models-lock":
        from .profiles import lock_profiles

        print(canonical(lock_profiles(args.models_config, args.profile, args.output)))
        return
    if args.command == "publish" and args.run_id.startswith("release-"):
        from .release import publish

        if args.parquet_only:
            from .publication import publish_parquet as publish
        from .jobs import file_lock

        store = Store(args.workspace, readonly=True)
        try:
            with file_lock(
                args.workspace / "releases" / (args.run_id + ".publish.lock")
            ):
                print(canonical(publish(store, args.run_id, args.repo)))
        finally:
            store.close()
        return
    # Explicit environment configuration; never load arbitrary repository .env files.
    if args.command == "_crawl":
        from .crawl import crawl

        crawl(args.workspace, args.run_id, args.source, args.offline)
        return
    if args.command == "job-report":
        from .job_report import report

        print(canonical(report(args.workspace, args.job_id)))
        return
    if args.command in {
        "enrich",
        "enrich-resume",
        "enrich-repair",
        "job-status",
    }:
        from .jobs import Jobs

        jobs = Jobs(args.workspace)
        try:
            if args.command == "enrich":
                if args.limit < 0:
                    raise ValueError("limit must be nonnegative")
                job = jobs.create(
                    args.run_id,
                    args.models_config,
                    args.profile,
                    args.task,
                    args.limit,
                    course_ids=args.course,
                    reuse_job_ids=args.reuse_job,
                    allow_partial_reuse=args.allow_partial_reuse,
                )
                print(f"Created enrichment job {job}", flush=True)
                result = jobs.status(job) if args.prepare_only else jobs.run(job)
            elif args.command == "enrich-repair":
                from .repair import create_repair

                job = create_repair(
                    jobs,
                    args.job_id,
                    args.models_config,
                    args.profile,
                    args.limit,
                    args.course,
                    args.turns,
                    task_path=args.task,
                )
                print(f"Created repair job {job}", flush=True)
                result = jobs.status(job) if args.prepare_only else jobs.run(job)
            elif args.command == "enrich-resume":
                result = jobs.run(
                    args.job_id,
                    concurrency=args.concurrency,
                    request_timeout=args.request_timeout_seconds,
                )
            else:
                result = jobs.status(args.job_id)
        finally:
            jobs.close()
        print(canonical(result))
        return
    if args.command == "public-export":
        from .public_data import export_public

        print(
            canonical({"release": str(export_public(args.workspace, args.release_id))})
        )
        return
    readonly = args.command in {"status", "validate", "release"}
    store = Store(args.workspace, readonly=readonly)
    try:
        if args.command == "release":
            from .lifecycle import release

            print(
                canonical(
                    {
                        "release": str(
                            release(store, args.run_id, enrichment_ids=args.enrichment)
                        )
                    }
                )
            )
            return
        if args.command == "validate":
            from .release import validate

            print(
                canonical(
                    validate(
                        store,
                        args.run_id,
                    )
                )
            )
            return
        if args.command == "status":
            info = store.run(args.run_id)
            print(
                canonical(
                    {
                        "run_id": info["run_id"],
                        "semester": info["semester"],
                        "status": info["status"],
                        "revision": info["revision"],
                        "observed_at": info["observed_at"],
                        "origin": info["origin"],
                        "source_revision": info["source_revision"],
                        "stages": [
                            dict(r)
                            for r in store.db.execute(
                                select(
                                    stages.c.stage,
                                    stages.c.status,
                                    stages.c.error,
                                    stages.c.updated_at,
                                ).where(stages.c.run_id == args.run_id),
                            )
                        ],
                    }
                )
            )
            return
        with store.lock():
            if args.command in {"run", "scrape"}:
                if not re.fullmatch(r"\d{4}", args.semester):
                    raise ValueError("Use the four-digit UW term code")
                if not os.environ.get("MADGRADES_API_KEY"):
                    raise ValueError("MADGRADES_API_KEY is required")
                if shutil.disk_usage(store.root).free < 10 * 1024**3:
                    raise ValueError(
                        "At least 10 GiB free is required for a new run; model downloads may require more"
                    )
                from uwcourses.http_utils import get_user_agent

                config = {
                    "http": {
                        "concurrency": args.concurrency,
                        "per_domain": args.per_domain,
                        "target_concurrency": args.target_concurrency,
                        "download_delay": args.download_delay,
                    },
                    "workflow": "snapshot-v1",
                    "sources": list(SOURCES),
                    "ratings_contract": 1,
                    "user_agent": get_user_agent(),
                    "code_hash": code_hash(),
                }
                from .crawl import http_settings

                http_settings(config)
                run = store.new_run(args.semester, config)
                print(f"Created run {run}", flush=True)
                result = execute(store, run)
            elif args.command in {"refresh-instructors", "refresh-buildings"}:
                from .lifecycle import prepare_source_refresh

                source = args.command.removeprefix("refresh-")
                run = prepare_source_refresh(
                    store, args.run_id, source, args.source_workspace
                )
                print(f"Created {source} refresh run {run}", flush=True)
                result = execute(store, run)
            elif args.command == "resume":
                result = execute(store, args.run_id)
            elif args.command == "publish":
                from .release import publish

                if args.parquet_only:
                    from .publication import publish_parquet as publish

                result = publish(store, args.run_id, args.repo)
            elif args.command == "replay":
                info = store.run(args.run_id)
                config = json.loads(info["config_json"])
                config.update(
                    code_hash=code_hash(),
                    replay_from=args.run_id,
                    sources=list(SOURCES),
                    ratings_contract=1,
                )
                run = store.new_run(info["semester"], config)
                with store.db:
                    store.db.execute(
                        insert(responses).from_select(
                            list(responses.c.keys()),
                            select(
                                literal(run),
                                responses.c.source,
                                responses.c.fingerprint,
                                responses.c.url,
                                responses.c.status,
                                responses.c.content_type,
                                responses.c.body_hash,
                                responses.c.fetched_at,
                            ).where(responses.c.run_id == args.run_id),
                        ),
                    )
                print(f"Created replay run {run}", flush=True)
                for source in SOURCES[: SOURCES.index(args.source) + 1]:
                    execute_source(store, run, source, offline=True)
                result = {
                    "run_id": run,
                    "source": args.source,
                    "status": "complete",
                    "next": f"resume {run}",
                }
            print(canonical(result))
    finally:
        store.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
