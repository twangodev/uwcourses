import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from uwcourses.skills_pilot import annotations, build, partition, read_guide


HTML = """<div class="site-tagline">2026-2027</div>
<div class="courseblock">
<p class="courseblocktitle noindent"><span class="courseblockcode">COMP SCI/STAT 300</span> — Computing</p>
<p class="courseblockdesc noindent">Write computer programs.</p>
<p><span class="cbextra-label">Learning Outcomes:</span><span class="cbextra-data">1. Implement algorithms.<br/>Audience: Undergraduate</span></p>
</div>"""


class SkillsPilotTests(unittest.TestCase):
    def test_source_archive_and_pending_labels_are_honest(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "guide.html", Path(directory) / "pilot"
            source.write_text(HTML)
            report = build([("comp_sci", source)], output)
            self.assertEqual(report["pilot_courses"], 1)
            self.assertEqual(report["manually_reviewed_decisions"], 0)
            self.assertFalse(report["automatic_classification_enabled"])
            self.assertEqual(
                report["sources"][0]["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                (output / "sources/comp_sci.html").read_bytes(), source.read_bytes()
            )
            rows = [
                json.loads(line)
                for line in (output / "annotations.pending.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(len(rows), 6)
            self.assertTrue(
                all(row["reviewed"] is False and row["gold"] is None for row in rows)
            )
            self.assertEqual(
                {row["split"] for row in rows}, {partition(rows[0]["course_identity"])}
            )
            self.assertEqual(set(rows[0]["aliases"]), {"COMPSCI 300", "STAT 300"})
            self.assertTrue(
                all(row["quote"] == "Implement algorithms." for row in rows)
            )
            with self.assertRaises(FileExistsError):
                build([("comp_sci", source)], output)

    def test_source_error_page_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.html"
            path.write_text("<h1>403 ERROR</h1>")
            with self.assertRaisesRegex(ValueError, "No course blocks"):
                read_guide("comp_sci", path)

    def test_long_evidence_is_never_silently_truncated(self):
        course = {
            "course_id": "COMPSCI 300",
            "course_reference": {"subjects": ["COMPSCI"], "course_number": 300},
            "official_learning_outcomes": [
                {"text": "x" * 1801, "source_url": "https://guide.wisc.edu/"}
            ],
            "description": "short",
            "source_url": "https://guide.wisc.edu/",
        }
        self.assertEqual(annotations([course]), [])


if __name__ == "__main__":
    unittest.main()
