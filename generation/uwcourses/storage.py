"""Inspect workspace roles and compact private databases without pruning history."""

from contextlib import ExitStack
import hashlib
from pathlib import Path
import struct

from .database import Database
from .jobs import file_lock
from .migrate import upgrade_database

ROLES = {
    "pipeline.sqlite": "durable source observations and scrape checkpoints",
    "processing.sqlite": "durable job inputs, results and retry state; includes a reusable output cache",
    "course-identities.json": "durable course identity registry",
    "raw": "durable compressed source evidence",
    "releases": "retained immutable releases",
    "runs": "run configuration, logs and scrape resume state",
    "jobs": "job locks and execution metadata",
    "inference-venv": "rebuildable inference environment",
    "runtime-cache": "rebuildable compiled kernels and runtime cache",
    "builds": "rebuildable serving projections",
    "models": "rebuildable embeddings and model cache links",
}
REBUILDABLE = {"inference-venv", "runtime-cache", "builds", "models"}


def allocated_bytes(root):
    seen, total = set(), 0
    for path in [root] if root.is_file() else root.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        key = (info.st_dev, info.st_ino)
        if key not in seen:
            seen.add(key)
            total += info.st_blocks * 512
    return total


def report(workspace):
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace must be an existing directory")
    entries = []
    for path in sorted(workspace.iterdir()):
        role = ROLES.get(path.name, "unclassified; inspect before removing")
        if path.is_symlink():
            role = "external link; target space is not counted"
        elif path.name.endswith(("-wal", "-shm")):
            role = "SQLite transaction state; never remove manually"
        elif path.is_dir() and (path / "pipeline.sqlite").is_file():
            role = "nested workspace with durable source state"
        entries.append(
            {
                "path": path.name,
                "bytes": allocated_bytes(path),
                "role": role,
                "rebuildable": path.name in REBUILDABLE and not path.is_symlink(),
            }
        )
    return {"workspace": str(workspace), "entries": entries}


def fingerprint(db):
    digest = hashlib.sha256()
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version' ORDER BY name"
    ).fetchall()
    for (name,) in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        columns = db.execute(f"PRAGMA table_info({quoted})").fetchall()
        primary = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        order = ",".join('"' + key.replace('"', '""') + '"' for key in primary)
        order = order or "rowid"
        digest.update(name.encode() + b"\0")
        for row in db.execute(f"SELECT * FROM {quoted} ORDER BY {order}"):
            digest.update(b"row\0")
            for value in row:
                raw = value if isinstance(value, bytes) else str(value).encode()
                digest.update(type(value).__name__.encode() + b"\0")
                digest.update(struct.pack("<Q", len(raw)))
                digest.update(raw)
    return digest.hexdigest()


def checkpoint(db):
    result = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    db.commit()
    if result[0]:
        raise RuntimeError("Database has active readers; retry maintenance when idle")


def compact(workspace, progress=None):
    workspace = Path(workspace).resolve()
    if not workspace.is_dir():
        raise ValueError("Workspace must be an existing directory")
    results = []
    with ExitStack() as locks:
        locks.enter_context(file_lock(workspace / "storage.lock"))
        locks.enter_context(file_lock(workspace / "pipeline.lock"))
        for lock in sorted((workspace / "jobs").glob("*.lock")):
            locks.enter_context(file_lock(lock))
        for kind, name in (
            ("pipeline", "pipeline.sqlite"),
            ("processing", "processing.sqlite"),
        ):
            path = workspace / name
            if not path.is_file():
                continue
            if path.is_symlink() or path.stat().st_nlink != 1:
                raise ValueError(f"Refusing to compact a linked database: {path}")
            db = Database(path, timeout=0)
            try:
                if progress:
                    progress(
                        f"{name}: verifying every logical value and compressing payloads"
                    )
                before = (
                    db.execute("PRAGMA page_count").fetchone()[0]
                    * db.execute("PRAGMA page_size").fetchone()[0]
                )
                db.rollback()
                stamp = upgrade_database(db, kind, fingerprint=fingerprint)
                checkpoint(db)
                if progress:
                    progress(f"{name}: reclaiming free pages")
                db.execute("VACUUM")
                db.commit()
                checkpoint(db)
                if progress:
                    progress(f"{name}: checking integrity and foreign keys")
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError(f"Database integrity check failed: {path}")
                if db.execute("PRAGMA foreign_key_check").fetchone():
                    raise ValueError(f"Database foreign key check failed: {path}")
                results.append(
                    {
                        "path": name,
                        "before_bytes": before,
                        "after_bytes": path.stat().st_size,
                        "logical_sha256": stamp,
                    }
                )
            finally:
                db.close()
    return {"workspace": str(workspace), "databases": results}
