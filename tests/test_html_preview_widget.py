from __future__ import annotations

import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication

from scripts.ui.widgets.html_preview_widget import HtmlPreviewWidget, is_html_previewable


class HtmlPreviewWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_is_html_previewable_accepts_html_extensions(self):
        self.assertTrue(is_html_previewable("scripts_user/report.html"))
        self.assertTrue(is_html_previewable("scripts_user/report.HTM"))

    def test_is_html_previewable_rejects_other_files(self):
        self.assertFalse(is_html_previewable("scripts_user/report.py"))
        self.assertFalse(is_html_previewable("scripts_user/report.txt"))
        self.assertFalse(is_html_previewable(None))

    def test_scrollbar_css_contains_themeable_webkit_rules(self):
        css = HtmlPreviewWidget._build_scrollbar_css()
        self.assertIn("::-webkit-scrollbar", css)
        self.assertIn("::-webkit-scrollbar-thumb", css)
        self.assertIn("scrollbar-width: thin", css)

    def test_shell_template_exists(self):
        template_path = os.path.abspath(
            os.path.join(
                PROJECT_ROOT,
                "plugins",
                "ai_assistant",
                "ui",
                "resources",
                "html_preview_template.html",
            )
        )
        self.assertTrue(os.path.exists(template_path))


if __name__ == "__main__":
    unittest.main()
