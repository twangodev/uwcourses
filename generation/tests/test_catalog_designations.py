import logging
import unittest

from bs4 import BeautifulSoup

from uwcourses.course import Course


def course_from(html):
    block = BeautifulSoup(html, "html.parser").select_one(".courseblock")
    return Course.from_block(block, logging.getLogger("test"))


BLOCK = """
<div class="courseblock">
<p class="courseblocktitle noindent"><span class="courseblockcode">COMP SCI 300</span> — Programming II</p>
<p class="courseblockdesc noindent">Object-oriented programming.</p>
<div class="cb-extras">
<p class="courseblockextra"><span class="cbextra-label"><strong>Requisites:</strong></span><span class="cbextra-data"><a title="COMP SCI 200">COMP SCI 200</a> or placement</span></p>
<p class="courseblockextra"><span class="cbextra-label"><strong>Course Designation:</strong></span><span class="cbextra-data">Core GenEd - Mathematics &amp; Quantitative Reasoning<br>Comm QR - Quantitative Reasoning B<br>Breadth - Natural Science<br>Level - Intermediate<br>L&amp;S Credit - L&amp;S Liberal Arts and Science</span></p>
</div>
</div>
"""


class CatalogDesignationTests(unittest.TestCase):
    def test_designation_lines_stay_with_requisites(self):
        course = course_from(BLOCK)
        self.assertEqual(
            course.designations,
            [
                "Core GenEd - Mathematics & Quantitative Reasoning",
                "Comm QR - Quantitative Reasoning B",
                "Breadth - Natural Science",
                "Level - Intermediate",
                "L&S Credit - L&S Liberal Arts and Science",
            ],
        )
        self.assertIn("COMP SCI 200", course.prerequisites.prerequisites_text)
        self.assertIn("designations", course.to_dict())

    def test_designation_without_requisites_is_kept(self):
        course = course_from(
            """
            <div class="courseblock">
            <p class="courseblocktitle noindent"><span class="courseblockcode">COMP SCI 300</span> — Programming II</p>
            <p class="courseblockdesc noindent">Object-oriented programming.</p>
            <div class="cb-extras"><span class="cbextra-label">Course Designation:</span><span class="cbextra-data">Breadth - Natural Science</span></div>
            </div>
            """
        )
        self.assertEqual(course.designations, ["Breadth - Natural Science"])
        self.assertEqual(course.prerequisites.prerequisites_text, "")
