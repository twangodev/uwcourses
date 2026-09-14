import sqlite3
import unittest

from web.blog.evidence import generate, summarize


class BlogEvidenceTests(unittest.TestCase):
    def test_weights_each_grade_not_each_term(self):
        small = dict(a=1, ab=0, b=0, bc=0, c=0, d=0, f=0)
        large = dict(a=0, ab=0, b=0, bc=0, c=0, d=0, f=9)
        result = summarize([small, large])
        self.assertEqual(result["n"], 10)
        self.assertAlmostEqual(result["gpa"], 0.4)
        self.assertEqual(result["a_percent"], 10)

    def test_ab_counts_as_three_point_five_but_not_an_a(self):
        result = summarize([dict(a=0, ab=2, b=0, bc=0, c=0, d=0, f=0)])
        self.assertEqual(result["gpa"], 3.5)
        self.assertEqual(result["a_percent"], 0)

    def test_empty_history_has_no_average(self):
        self.assertIsNone(summarize([])["gpa"])

    def test_rejects_future_grade_window(self):
        with sqlite3.connect(":memory:") as db:
            with self.assertRaisesRegex(ValueError, "precede"):
                generate(
                    {"start_term": "1222", "end_term": "1274", "target_term": "1274"},
                    db,
                    {},
                )


if __name__ == "__main__":
    unittest.main()
