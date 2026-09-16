"""Regression tests for missing images in copied nested reports."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from validate_report_links import check_report_links


class ReportLinksTests(unittest.TestCase):
    def test_nested_single_quoted_missing_image_is_detected(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "index.html").write_text('<a href="report/report.html">Report</a>')
            (root / "report").mkdir()
            (root / "report/report.html").write_text("<img src='../images/leaf.png'>")
            with self.assertRaisesRegex(AssertionError, "leaf.png"):
                check_report_links(root)
            (root / "images").mkdir()
            (root / "images/leaf.png").write_bytes(b"fixture")
            self.assertEqual(check_report_links(root), (2, 2))

    def test_external_fragment_and_encoded_url(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "leaf image.png").write_bytes(b"fixture")
            (root / "index.html").write_text(
                '<a href="https://example.org">external</a><a href="#section">jump</a>'
                '<img src="leaf%20image.png?v=1#preview">'
            )
            self.assertEqual(check_report_links(root), (1, 1))


if __name__ == "__main__":
    unittest.main()
