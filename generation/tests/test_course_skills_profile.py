"""The new model stays opt-in and uses the shared immutable identity mechanism."""

import unittest
from pathlib import Path
from unittest.mock import patch

from uwcourses.profiles import load_profile


class CourseSkillsProfileTests(unittest.TestCase):
    def test_dense_model_is_separate_and_revision_resolved(self):
        config = Path(__file__).resolve().parents[2] / "inference/models.toml"
        with patch("huggingface_hub.HfApi") as hub:
            hub.return_value.model_info.return_value.sha = "c" * 40
            profile = load_profile(config, "course-skills-qwen38")
        self.assertEqual(profile.model, "Qwen/Qwen3.8-27B")
        self.assertEqual(profile.revision, "c" * 40)
        self.assertEqual(profile.concurrency, 4)
        self.assertEqual(profile.temperature, 0.0)
        self.assertEqual(profile.served_model, "Qwen/Qwen3.8-27B@" + "c" * 40)
        with patch("huggingface_hub.HfApi") as hub:
            hub.return_value.model_info.return_value.sha = "d" * 40
            existing = load_profile(config, "enrichment-unified")
        self.assertEqual(existing.model, "nvidia/Qwen3.6-35B-A3B-NVFP4")
