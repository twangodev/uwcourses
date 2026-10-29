"""Launch an isolated vLLM server from a locked model profile."""

import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument(
        "--models-config",
        type=Path,
        required=True,
        help="Pinned profile file produced by coursemap models-lock",
    )
    parser.add_argument("--profile", default="enrichment")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from uwcourses.profiles import load_profile
    from urllib.parse import urlparse

    try:
        profile = load_profile(args.models_config, args.profile, resolve=False)
    except ValueError as exc:
        parser.error(f"{exc}. Create pinned profiles with coursemap models-lock first.")
    if profile.engine != "vllm" or profile.engine_version != "0.28.0":
        raise ValueError(
            "This launcher uses the locked vLLM 0.28.0 runtime; launch other runtimes separately"
        )
    url = urlparse(profile.base_url)
    if url.hostname not in {"127.0.0.1", "localhost"} or url.scheme != "http":
        raise ValueError("The local launcher requires a loopback HTTP endpoint")
    reserved = {
        "--host",
        "--port",
        "--revision",
        "--tokenizer-revision",
        "--served-model-name",
        "--runner",
        "--max-model-len",
    }
    if any(arg.split("=", 1)[0] in reserved for arg in profile.server_args):
        raise ValueError(
            "Server arguments must not override profile identity or endpoint"
        )
    env = dict(os.environ)
    # FlashInfer JIT kernels need the toolkit compiler, not just the driver.
    toolkit = Path(env.get("CUDA_HOME", "/usr/local/cuda"))
    if (toolkit / "bin" / "nvcc").is_file():
        env["CUDA_HOME"] = str(toolkit)
        env["PATH"] = str(toolkit / "bin") + os.pathsep + env.get("PATH", "")
    # Keep vLLM's dependency graph independent of the scraper's environment.
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("VIRTUAL_ENV", None)
    env["UV_PROJECT_ENVIRONMENT"] = str(args.workspace.resolve() / "inference-venv")
    env.setdefault(
        "HF_HOME",
        str(Path(env.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "huggingface"),
    )
    env["XDG_CACHE_HOME"] = str(args.workspace.resolve() / "runtime-cache")
    env["VLLM_NO_USAGE_STATS"] = "1"
    if env.get("COURSEMAP_INFERENCE_API_KEY"):
        env["VLLM_API_KEY"] = env["COURSEMAP_INFERENCE_API_KEY"]
    command = [
        "uv",
        "run",
        "--project",
        str(Path(__file__).resolve().parents[1] / "inference"),
        "--locked",
        "vllm",
        "serve",
        profile.model,
        "--revision",
        profile.revision,
        "--tokenizer-revision",
        profile.revision,
        "--served-model-name",
        profile.served_model,
        "--runner",
        profile.runner,
        "--host",
        "127.0.0.1",
        "--port",
        str(url.port or 80),
        "--max-model-len",
        str(profile.context_length),
        *profile.server_args,
    ]
    if args.dry_run:
        import shlex

        print(shlex.join(command))
        return
    subprocess.run(command, env=env, check=True)


if __name__ == "__main__":
    main()
