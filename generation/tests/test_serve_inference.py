import os
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ServeInferenceTests(unittest.TestCase):
    def test_shared_model_cache_survives_runtime_cache_isolation(self):
        launcher = Path(__file__).resolve().parents[2] / "scripts/serve_inference.py"
        profile = SimpleNamespace(
            engine="vllm",
            engine_version="0.28.0",
            base_url="http://127.0.0.1:8000",
            server_args=[],
            model="test/model",
            revision="a" * 40,
            served_model="test/model@" + "a" * 40,
            runner="generate",
            context_length=4096,
        )
        cases = [
            ({}, "/home/test/.cache/huggingface"),
            ({"XDG_CACHE_HOME": "/shared/cache"}, "/shared/cache/huggingface"),
            (
                {"HF_HOME": "/shared/hf", "XDG_CACHE_HOME": "/other/cache"},
                "/shared/hf",
            ),
            (
                {"HF_HUB_CACHE": "/shared/hub"},
                "/home/test/.cache/huggingface",
            ),
            (
                {"HUGGINGFACE_HUB_CACHE": "/legacy/hub"},
                "/home/test/.cache/huggingface",
            ),
        ]
        for variables, expected in cases:
            with (
                self.subTest(variables=variables),
                patch.dict(os.environ, {"HOME": "/home/test", **variables}, clear=True),
                patch(
                    "sys.argv",
                    [
                        str(launcher),
                        "--workspace",
                        "/tmp/inference-workspace",
                        "--models-config",
                        "/tmp/models.lock.json",
                    ],
                ),
                patch("uwcourses.profiles.load_profile", return_value=profile),
                patch("subprocess.run") as launch,
            ):
                runpy.run_path(str(launcher), run_name="__main__")
                env = launch.call_args.kwargs["env"]
                self.assertEqual(env["HF_HOME"], expected)
                self.assertEqual(
                    env["XDG_CACHE_HOME"], "/tmp/inference-workspace/runtime-cache"
                )
                for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
                    self.assertEqual(env.get(key), variables.get(key))
