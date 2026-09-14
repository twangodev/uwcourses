import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1] / "seo_audit.py"
NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
ORIGIN = "https://uwcourses.com"


class SeoAuditTests(unittest.TestCase):
    def test_blog_sitemap_and_catalog_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".svelte-kit/cloudflare"
            (root / "blog").mkdir(parents=True)
            (root / "social").mkdir()
            (root / "social/manifest.json").write_text("[]")
            (root / "_worker.js").mkdir()
            (root / "blog/sitemap.xml").write_text(
                f"<urlset {NS}><url><loc>{ORIGIN}/blog</loc></url>"
                f"<url><loc>{ORIGIN}/blog/welcome</loc>"
                "<lastmod>2026-09-13</lastmod></url></urlset>"
            )
            for location, succeeds in [
                (f"{ORIGIN}/blog/sitemap.xml", True),
                ("https://example.com/blog/sitemap.xml", False),
                (f"{ORIGIN}/other/sitemap.xml", False),
            ]:
                with self.subTest(location=location):
                    (root / "sitemap.xml").write_text(
                        f"<sitemapindex {NS}><sitemap><loc>{location}</loc>"
                        "<lastmod>2026-09-13</lastmod></sitemap></sitemapindex>"
                    )
                    result = subprocess.run(
                        [sys.executable, str(AUDIT)],
                        cwd=directory,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode == 0, succeeds, result.stderr)
