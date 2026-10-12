"""Atomic Parquet-only publication with a minimal card and verified remote files."""

import hashlib
import json
from pathlib import Path

from .models import canonical, digest
from .public_data import dataset_card
from .release import checksum, sync_metadata, verify_release


def publish_parquet(store, release_id, repo_id, api=None, download=None):
    from huggingface_hub import HfApi, CommitOperationAdd, DatasetCard, hf_hub_download
    from .jobs import file_lock

    if Path(release_id).name != release_id:
        raise ValueError("Expected a release ID")
    with file_lock(store.root / "parquet-publication.lock"):
        directory = store.root / "releases" / release_id
        original = verify_release(directory)
        source = store.run(original["source_run"])
        if (
            source["status"] != "complete"
            or store.input_hash(source["run_id"]) != original["input_hash"]
        ):
            raise ValueError(
                "Publication requires a completed, unchanged source snapshot"
            )
        paths = {
            name: directory / name
            for name in original["files"]
            if name.startswith("public/")
            or (name.startswith("tables/") and name.endswith(".parquet"))
        }
        if not original.get("public_tables") or not original.get("tables"):
            raise ValueError(
                "Parquet publication requires both public and archive tables"
            )
        files = {name: original["files"][name] for name in paths}
        card = dataset_card(
            source["run_id"], original["public_tables"], original["tables"], repo_id
        )
        card_bytes = card.encode()
        paths["README.md"] = card_bytes
        files["README.md"] = {
            "bytes": len(card_bytes),
            "sha256": hashlib.sha256(card_bytes).hexdigest(),
        }
        manifest = {
            k: v for k, v in original.items() if k not in {"files", "website_included"}
        }
        manifest.update(
            format="parquet",
            public_schema_version=json.loads(
                (directory / "public/schema.json").read_text()
            )["version"],
            source_archive_release=release_id,
            source_archive_manifest_sha256=checksum(directory / "manifest.json"),
            files=files,
        )
        manifest_bytes = canonical(manifest).encode()
        paths["manifest.json"] = manifest_bytes
        sync = sync_metadata(
            original, source, None, original["public_tables"]["courses_current"]
        )
        sync.pop("data_revision")
        sync.update(
            data_release=release_id,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        )
        paths["sync.json"] = canonical(sync).encode()
        expected = {
            **files,
            **{
                name: {
                    "bytes": len(paths[name]),
                    "sha256": hashlib.sha256(paths[name]).hexdigest(),
                }
                for name in ["manifest.json", "sync.json"]
            },
        }
        api, download = api or HfApi(), download or hf_hub_download
        DatasetCard(card).validate()
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        head = api.repo_info(repo_id=repo_id, repo_type="dataset").sha
        existing = set(
            api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=head)
        ) - {".gitattributes"}
        if existing - paths.keys():
            raise ValueError(
                "Repository contains files outside this publication; refusing to remove them"
            )
        status_path = (
            store.root / "publications" / f"{release_id}-{digest(repo_id)[:12]}.json"
        )
        status_path.parent.mkdir(parents=True, exist_ok=True)

        def save(phase, **details):
            value = {
                "status": phase,
                "repo_id": repo_id,
                "release_id": release_id,
                **details,
            }
            temporary = status_path.with_suffix(".tmp")
            temporary.write_text(canonical(value))
            temporary.replace(status_path)
            return value

        save("uploading", base_revision=head)
        # Data, card, manifest and badges become visible in the same commit.
        result = api.create_commit(
            repo_id=repo_id,
            repo_type="dataset",
            parent_commit=head,
            operations=[
                CommitOperationAdd(
                    path_in_repo=name,
                    path_or_fileobj=str(value) if isinstance(value, Path) else value,
                )
                for name, value in sorted(paths.items())
            ],
            commit_message="Publish course dataset with RMP reviews and LLM metadata",
            num_threads=8,
        )
        revision = result.oid
        save("verifying", revision=revision)
        actual = set(
            api.list_repo_files(repo_id=repo_id, repo_type="dataset", revision=revision)
        ) - {".gitattributes"}
        if actual != set(paths):
            raise ValueError("Published file set differs from the release")
        infos = api.get_paths_info(
            repo_id=repo_id, paths=list(paths), repo_type="dataset", revision=revision
        )
        checked = set()
        for info in infos:
            checked.add(info.path)
            sha = (
                info.lfs.sha256
                if info.lfs
                else checksum(
                    Path(
                        download(
                            repo_id=repo_id,
                            filename=info.path,
                            repo_type="dataset",
                            revision=revision,
                        )
                    )
                )
            )
            if (
                info.size != expected[info.path]["bytes"]
                or sha != expected[info.path]["sha256"]
            ):
                raise ValueError(f"Remote checksum mismatch: {info.path}")
        if checked != set(paths):
            raise ValueError("Could not verify every published file")
        if api.repo_info(repo_id=repo_id, repo_type="dataset").sha != revision:
            raise ValueError(
                "HF main advanced during verification; published revision is still pinned in the checkpoint"
            )
        return save(
            "complete",
            revision=revision,
            parquet_files=sum(n.endswith(".parquet") for n in paths),
            bytes=sum(v["bytes"] for v in expected.values()),
        )


def safe_relative(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Publication manifest contains an unsafe path")
    return path


def verify_file(path, expected):
    if path.stat().st_size != expected["bytes"] or checksum(path) != expected["sha256"]:
        raise ValueError(f"Source publication checksum mismatch: {path.name}")


def publish_candidate(
    candidate, repo_id, parent_revision, *, commit_message, api=None, download=None
):
    """Publish verified supplement files atomically; preserve pinned remote parent."""
    from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

    candidate = Path(candidate)
    manifest = json.loads((candidate / "manifest.json").read_text())
    if manifest.get("parent_dataset_revision") != parent_revision:
        raise ValueError("Candidate does not identify the pinned dataset parent")
    sync = json.loads((candidate / "sync.json").read_text())
    if (
        sync.get("manifest_sha256") != checksum(candidate / "manifest.json")
        or sync.get("data_release") != manifest["run_id"]
    ):
        raise ValueError("Candidate sync metadata does not identify its manifest")
    expected = dict(manifest["files"])
    for name in ("manifest.json", "sync.json"):
        expected[name] = {
            "bytes": (candidate / name).stat().st_size,
            "sha256": checksum(candidate / name),
        }
    for name, metadata in expected.items():
        verify_file(candidate / safe_relative(name), metadata)
    api, download = api or HfApi(), download or hf_hub_download
    if api.repo_info(repo_id=repo_id, repo_type="dataset").sha != parent_revision:
        raise ValueError("Dataset main changed since the candidate was prepared")
    existing = set(
        api.list_repo_files(repo_id, repo_type="dataset", revision=parent_revision)
    ) - {".gitattributes"}
    if not existing <= expected.keys():
        raise ValueError("Candidate omits files from the current dataset")
    checkpoint = candidate.parent / f"{manifest['run_id']}-publication.json"
    checkpoint.write_text(
        canonical(
            {
                "status": "uploading",
                "repo_id": repo_id,
                "parent_revision": parent_revision,
                "release_id": manifest["run_id"],
            }
        )
    )
    result = api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        parent_commit=parent_revision,
        commit_message=commit_message,
        operations=[
            CommitOperationAdd(path_in_repo=name, path_or_fileobj=str(candidate / name))
            for name in sorted(expected)
        ],
        num_threads=8,
    )
    revision = result.oid
    checkpoint.write_text(
        canonical(
            {
                "status": "verifying",
                "repo_id": repo_id,
                "parent_revision": parent_revision,
                "revision": revision,
                "release_id": manifest["run_id"],
            }
        )
    )
    actual = set(
        api.list_repo_files(repo_id, repo_type="dataset", revision=revision)
    ) - {".gitattributes"}
    if actual != expected.keys():
        raise ValueError("Published supplement file set differs from the candidate")
    checked = set()
    for info in api.get_paths_info(
        repo_id=repo_id, paths=list(expected), repo_type="dataset", revision=revision
    ):
        checked.add(info.path)
        sha = (
            info.lfs.sha256
            if info.lfs
            else checksum(
                Path(
                    download(
                        repo_id=repo_id,
                        filename=info.path,
                        repo_type="dataset",
                        revision=revision,
                    )
                )
            )
        )
        if (
            info.size != expected[info.path]["bytes"]
            or sha != expected[info.path]["sha256"]
        ):
            raise ValueError(f"Remote supplement checksum mismatch: {info.path}")
    if (
        checked != expected.keys()
        or api.repo_info(repo_id=repo_id, repo_type="dataset").sha != revision
    ):
        raise ValueError("Dataset changed during remote supplement verification")
    report = {
        "repo_id": repo_id,
        "revision": revision,
        "parent_revision": parent_revision,
        "release_id": manifest["run_id"],
        "verified_files": len(checked),
        "status": "complete",
    }
    checkpoint.write_text(canonical(report))
    return report
