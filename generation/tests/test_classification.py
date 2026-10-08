import copy
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from uwcourses.classification import (
    evaluate,
    predict,
    questions,
    validate_inputs,
    LABELS,
    TAXONOMY_VERSION,
)


def row(index=0, split="eval", gold=True, score=0.99, label="programming"):
    return {
        "course_id": f"COMP SCI {index}",
        "course_identity": f"course-{index}",
        "aliases": [f"CS {index}"],
        "source_id": f"source-{index}",
        "source_url": "https://guide.wisc.edu/courses/comp_sci/",
        "passage": "Develop and debug computer programs.",
        "quote": "Develop and debug computer programs.",
        "label": label,
        "split": split,
        "gold": gold,
        "reviewed": True,
        "model_id": "fixture-not-a-model-run",
        "model_revision": "a" * 40,
        "taxonomy_version": TAXONOMY_VERSION,
        "probabilities": {
            "yes": score,
            "no": (1 - score) / 2,
            "unknown": (1 - score) / 2,
        },
        "reversed_probabilities": {
            "yes": score,
            "no": (1 - score) / 2,
            "unknown": (1 - score) / 2,
        },
    }


class ClassificationTests(unittest.TestCase):
    def test_unreviewed_template_cannot_be_evaluated(self):
        item = row(gold=None)
        item["reviewed"] = False
        with self.assertRaisesRegex(ValueError, "manually reviewed"):
            evaluate([item])

    def test_no_automatic_categories_without_evaluation(self):
        report = evaluate([row()])
        self.assertFalse(
            any(value["enabled"] for value in report["categories"].values())
        )
        self.assertIsNone(report["decisions_per_second"])

    def test_alias_leakage_and_quote_rejection(self):
        first, second = row(1), row(2, split="calibration")
        second["aliases"] = [first["course_id"]]
        with self.assertRaisesRegex(ValueError, "leaks"):
            validate_inputs([first, second])
        second["aliases"] = []
        second["quote"] = "Unstated workload estimate."
        with self.assertRaisesRegex(ValueError, "exactly"):
            validate_inputs([second])

    def test_threshold_uses_only_calibration(self):
        rows = [row(i, split="calibration", score=0.9) for i in range(20)]
        rows += [row(100 + i, score=0.89) for i in range(100)]
        report = evaluate(rows)["categories"]["programming"]
        self.assertEqual(report["threshold"], 0.9)
        self.assertEqual(report["accepted"], 0)
        self.assertFalse(report["enabled"])

    def test_category_gate_and_unknown_precision(self):
        rows = [row(i, split="calibration") for i in range(20)]
        rows += [row(100 + i) for i in range(100)]
        rows += [row(300 + i, gold=None, score=0.01) for i in range(10)]
        unrelated = [row(400 + i, gold=False, score=0.01) for i in range(10)]
        for value in unrelated:
            value["case_kind"] = "unrelated"
        rows += unrelated
        report = evaluate(rows)
        self.assertTrue(report["categories"]["programming"]["enabled"])
        self.assertTrue(
            all(
                not v["enabled"]
                for k, v in report["categories"].items()
                if k != "programming"
            )
        )
        mutated = copy.deepcopy(rows)
        mutated[20]["gold"] = None
        self.assertEqual(
            evaluate(mutated)["categories"]["programming"]["precision"], 0.99
        )
        for value in mutated[20:24]:
            value["gold"] = None
        self.assertFalse(evaluate(mutated)["categories"]["programming"]["enabled"])

    def test_order_sensitivity_disables_gate(self):
        rows = [row(i, split="calibration") for i in range(20)] + [
            row(100 + i) for i in range(100)
        ]
        rows += [row(300 + i, gold=None, score=0.01) for i in range(10)]
        for i in range(10):
            item = row(400 + i, gold=False, score=0.01)
            item["case_kind"] = "unrelated"
            rows.append(item)
        rows[20]["reversed_probabilities"] = {"yes": 0.5, "no": 0.3, "unknown": 0.2}
        self.assertFalse(evaluate(rows)["categories"]["programming"]["enabled"])

    def test_invalid_probabilities_revision_taxonomy_and_duplicates(self):
        for field, value in [
            ("model_revision", "main"),
            ("taxonomy_version", "v0"),
            ("probabilities", {"yes": float("nan"), "no": 0, "unknown": 0}),
        ]:
            item = row()
            item[field] = value
            with self.assertRaises(ValueError):
                evaluate([item])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            evaluate([row(), row()])
        with self.assertRaisesRegex(ValueError, "one immutable"):
            item = row(2)
            item["model_revision"] = "b" * 40
            evaluate([row(), item])

    def test_pinned_sdk_loads_exact_local_snapshot(self):
        calls = []

        class Agent:
            def predict(self, state, question):
                return {
                    "answers": {
                        label: {
                            "probabilities": {"yes": 0.8, "no": 0.1, "unknown": 0.1}
                        }
                        for label in question
                    }
                }

        def snapshot_download(*, repo_id, revision, allow_patterns):
            calls.append((repo_id, revision, allow_patterns))
            return "/tmp/test-pinned-snapshot"

        # Match the installed pinned SDK API: no revision keyword accepted.
        def load(local_path, device=None):
            calls.append((local_path, device))
            return Agent()

        with patch.dict(
            "sys.modules",
            {
                "laya": SimpleNamespace(load=load),
                "huggingface_hub": SimpleNamespace(snapshot_download=snapshot_download),
            },
        ):
            result = predict([row()], "c" * 40, device="cpu")
        self.assertEqual(calls[0][0:2], ("convaiinnovations/laya", "c" * 40))
        self.assertEqual(
            calls[0][2],
            ["rl_agent_config.json", "model.safetensors", "tokenizer/*", "encoder/*"],
        )
        self.assertEqual(calls[1], ("/tmp/test-pinned-snapshot", "cpu"))
        self.assertEqual(result[0]["model_revision"], "c" * 40)

    def test_runtime_refuses_truncated_evidence(self):
        class Tokenizer:
            mask_token = "[MASK]"

            def __call__(self, state, **kwargs):
                return {"input_ids": list(range(400))}

        class Agent:
            tok = Tokenizer()
            cfg = {"max_len": 512, "head_max_len": 192}

        with self.assertRaisesRegex(ValueError, "token budget"):
            predict([row()], "a" * 40, agent=Agent())

    def test_optional_runtime_adapter_retains_evidence(self):
        class Agent:
            def predict(self, state, question):
                return {
                    "answers": {
                        label: {
                            "probabilities": {"yes": 0.8, "no": 0.1, "unknown": 0.1}
                        }
                        for label in question
                    }
                }

        result = predict([row()], "b" * 40, agent=Agent())[0]
        self.assertEqual(result["quote"], row()["quote"])
        self.assertEqual(result["model_revision"], "b" * 40)
        self.assertEqual(result["taxonomy_version"], TAXONOMY_VERSION)
        self.assertGreater(result["elapsed_seconds"], 0)
        self.assertEqual(
            list(questions("writing", True)["writing"]["criteria"]),
            ["unknown", "no", "yes"],
        )
        self.assertEqual(len(LABELS), 6)


if __name__ == "__main__":
    unittest.main()
