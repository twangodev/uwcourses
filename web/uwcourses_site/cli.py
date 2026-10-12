"""Website build commands, independent of scraping and inference."""

import argparse
import json
from pathlib import Path
import sys


def check_assets(root: Path):
    files = [
        p
        for p in root.rglob("*")
        if p.is_file() and "_worker.js" not in p.relative_to(root).parts
    ]
    if not files:
        raise ValueError("No built assets found")
    largest = max(files, key=lambda p: p.stat().st_size)
    # Keep 10,000 files of headroom below Workers Paid's 100,000-asset limit.
    if len(files) > 90000:
        raise ValueError(f"Asset count {len(files)} exceeds 90,000")
    if largest.stat().st_size > 20 * 1024 * 1024:
        raise ValueError(f"Asset exceeds 20 MiB: {largest}")
    report = {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "largest": str(largest),
        "largest_bytes": largest.stat().st_size,
    }
    print(json.dumps(report, indent=2))
    return report


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {
        "resolve",
        "cache-check",
        "cache-seal",
        "cache-verify",
    }:
        from . import build_cache

        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("command")
        parser.add_argument("--stage", choices=list(build_cache.STAGES))
        parser.add_argument("--revision")
        args = parser.parse_args()
        if args.command == "resolve":
            build_cache.resolve(args.revision)
        elif not args.stage:
            parser.error("--stage is required")
        elif args.command == "cache-seal":
            build_cache.seal(args.stage)
        elif args.command == "cache-verify":
            if not build_cache.valid(args.stage):
                raise ValueError(f"Invalid {args.stage} cache")
        else:
            build_cache.outputs({"valid": build_cache.valid(args.stage)})
        return
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        from .importer import main as import_main

        del sys.argv[1]
        import_main()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "command",
            choices=["assets-check", "release-check", "deploy", "smoke-check"],
        )
        parser.add_argument("--root", type=Path, default=Path(".svelte-kit/cloudflare"))
        parser.add_argument("--site", type=Path, default=Path(".site/import"))
        parser.add_argument("--config", type=Path, default=Path("wrangler.json"))
        parser.add_argument("--first-deployment", action="store_true")
        parser.add_argument("--base-url", default="https://uwcourses.com")
        parser.add_argument("--commit")
        args = parser.parse_args()
        if args.command == "assets-check":
            check_assets(args.root)
        else:
            from .deployment import Release, deploy

            if args.command == "smoke-check":
                if not args.commit:
                    parser.error("smoke-check requires --commit")
                from .smoke import smoke_check

                smoke_check(
                    args.base_url, Release.read(args.site / "status.json"), args.commit
                )
            elif args.command == "release-check":
                release = Release.read(args.site / "status.json")
                print(f"Verified complete release {release.revision}")
            else:
                import os

                check_assets(args.root)
                deploy(
                    args.config,
                    args.site,
                    args.first_deployment
                    or os.environ.get("FIRST_DEPLOYMENT") == "true",
                )


if __name__ == "__main__":
    main()
