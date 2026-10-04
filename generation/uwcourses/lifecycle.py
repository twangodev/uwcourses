"""Independent immutable source snapshots, enrichment jobs, and releases."""

import json
import shutil

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert

from .schema import runs, observations
from .models import canonical, digest
from .store import Store, SOURCES


def scrape(store, run):
    from .cli import execute_source, code_hash
    from .reconcile import reconcile, encode_state
    from .release import validate

    info = store.run(run)
    if info["status"] == "complete":
        return {"run_id": run, "status": "complete"}
    config = json.loads(info["config_json"])
    if config["code_hash"] != code_hash():
        raise ValueError(
            "Scraper code changed; use replay to create a snapshot with new parser provenance"
        )
    with store.db:
        store.db.execute(
            update(runs).where(runs.c.run_id == run).values(status="running")
        )
    failures = []
    # Independent sources continue even if another source fails.
    for source in config["sources"]:
        if store.stage_status(run, source) == "complete":
            continue
        try:
            execute_source(store, run, source)
        except RuntimeError:
            failures.append(source)
    if failures:
        with store.db:
            store.db.execute(
                update(runs).where(runs.c.run_id == run).values(status="failed")
            )
        raise RuntimeError(
            f"Sources failed: {', '.join(failures)}; completed sources are checkpointed"
        )
    validate(store, run)
    state = encode_state(*reconcile(store, run))
    if not state["instructors"] or not any(state["meetings"].values()):
        raise ValueError(
            "Snapshot lacks reconciled instructors or target-semester meetings"
        )
    if (
        len(state["unmatched"]["offerings"])
        > len(store.records(run, "offerings")) * 0.1
    ):
        raise ValueError("More than 10% of offerings do not match catalog courses")
    store.artifact(
        run,
        "source_state",
        state,
        store.input_hash(run),
        {"inference": False, "code_hash": config["code_hash"]},
    )
    store.finish(run)
    return {"run_id": run, "status": "complete", "next": f"release {run}"}


def require_snapshot(store, run):
    if store.run(run)["status"] != "complete":
        raise ValueError("Processing requires a completed immutable source snapshot")
    if not store.db.execute(
        select(observations.c.entity_id)
        .where(observations.c.run_id == run, observations.c.kind == "courses")
        .limit(1)
    ).fetchone():
        raise ValueError(
            "Processing requires a course snapshot; auxiliary source runs cannot replace courses"
        )


def release(store, run, enrichment_ids=()):
    # One read transaction freezes the history selection while another scrape writes.
    store.db.execute("BEGIN")
    try:
        return _release(store, run, enrichment_ids)
    finally:
        store.db.rollback()


def _release(store, run, enrichment_ids):
    from .release import write_database, write_parquet, checksum, verify_release
    from . import SCHEMA_VERSION
    from .cli import code_hash
    import sqlite3

    require_snapshot(store, run)
    # Serialize release assembly without taking the source writer lock.
    from .jobs import file_lock, Jobs

    with file_lock(store.root / "releases.lock"):
        history = [
            (row["run_id"], store.input_hash(row["run_id"]))
            for row in store.db.execute(
                select(runs.c.run_id)
                .where(runs.c.status == "complete")
                .order_by(runs.c.run_id)
            )
        ]
        from .history import select_enrichments

        enrichment_history = select_enrichments(
            store.root, [key for key, _ in history], enrichment_ids, run
        )
        selection = {
            "source_run": run,
            "enrichment_history": enrichment_history,
            "history": history,
            "enrichment_ids": sorted(set(enrichment_ids)),
            "schema_version": SCHEMA_VERSION,
            "exporter_hash": code_hash(),
        }
        release_id = "release-" + digest(selection)[:24]
        target = store.root / "releases" / release_id
        if target.exists():
            verify_release(target)
            return target
        staging = target.with_name(target.name + ".partial")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        write_database(store, run, staging / "coursemap.sqlite")
        Jobs.append_release(
            store.root,
            staging / "coursemap.sqlite",
            run,
            enrichment_ids,
            enrichment_history,
        )
        counts = write_parquet(staging / "coursemap.sqlite", staging / "tables")
        from .public_data import write_public, dataset_card

        public_counts = write_public(
            staging / "coursemap.sqlite",
            staging,
            release_id,
            run,
            store.root / "course-identities.json",
        )
        with sqlite3.connect(staging / "coursemap.sqlite") as public:
            model_profiles = [
                json.loads(row[0])["profile"]
                for row in public.execute(
                    "SELECT spec_json FROM enrichment_jobs ORDER BY job_id"
                )
            ]
        model_ids = sorted(
            {f"{profile['model']}@{profile['revision']}" for profile in model_profiles}
        )
        model_citations = "\n".join(f"- `{identity}`" for identity in model_ids)
        (staging / "README.md").write_text(
            dataset_card(run, public_counts, counts)
            + (
                "\nGeneration models (pinned revisions):\n\n" + model_citations + "\n"
                if model_ids
                else ""
            )
        )
        manifest = {
            **selection,
            "run_id": release_id,
            "input_hash": store.input_hash(run),
            "observed_at": store.run(run)["observed_at"],
            "tables": counts,
            "public_tables": public_counts,
            "files": {
                p.relative_to(staging).as_posix(): {
                    "sha256": checksum(p),
                    "bytes": p.stat().st_size,
                }
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            },
        }
        (staging / "manifest.json").write_text(canonical(manifest))
        verify_release(staging)
        staging.replace(target)
        return target


def prepare_instructor_refresh(store, source_run, source_workspace=None):
    return prepare_source_refresh(store, source_run, "instructors", source_workspace)


def prepare_source_refresh(store, source_run, refreshed_source, source_workspace=None):
    """Reuse frozen core observations, preserving timestamps, in a new snapshot."""
    from .cli import code_hash

    source = Store(source_workspace or store.root, readonly=True)
    try:
        require_snapshot(source, source_run)
        info = source.run(source_run)
        if info["origin"] != "scrape":
            raise ValueError("Source refresh requires a native source snapshot")
        if refreshed_source not in {"instructors", "buildings"}:
            raise ValueError("Unsupported source refresh")
        config = json.loads(info["config_json"])
        reused = [
            name
            for name in SOURCES
            if name != refreshed_source
            and (
                name != "buildings"
                or source.stage_status(source_run, name) == "complete"
            )
        ]
        config.update(
            workflow="snapshot-v1",
            sources=list(SOURCES),
            code_hash=code_hash(),
            reused_sources={name: source_run for name in reused},
            reused_source_input_hash=source.input_hash(source_run),
        )
        if refreshed_source == "instructors":
            config["ratings_contract"] = 1
        run = store.new_run(info["semester"], config)
        for stage in reused:
            if source.stage_status(source_run, stage) != "complete":
                raise ValueError(f"Cannot reuse incomplete source: {stage}")
            with store.db:
                store.db.executemany(
                    insert(observations),
                    (
                        {**dict(row), "run_id": run}
                        for row in source.db.execute(
                            select(observations).where(
                                observations.c.run_id == source_run,
                                observations.c.source == stage,
                            ),
                        )
                    ),
                )
            store.stage(run, stage, "complete")
        return run
    finally:
        source.close()
