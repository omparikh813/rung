from django.conf import settings
from django.template import TemplateSyntaxError
from django.template.loader import render_to_string
from django.test import SimpleTestCase

from core.templatetags.rung import icon

STATUS_LABELS = {
    "new": "New",
    "denied": "Denied",
    "needs_fix": "Needs Fix",
    "ready": "Ready",
    "waiting": "Waiting on Specialist",
    "submitted": "Submitted",
    "closed": "Closed",
}


class IconTests(SimpleTestCase):
    def test_icon_is_inline_svg_hidden_from_screen_readers(self):
        svg = icon("check", "size-5")
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn('class="shrink-0 size-5"', svg)
        self.assertIn('aria-hidden="true"', svg)
        self.assertIn('stroke="currentColor"', svg)
        # The fixed 24 px size is removed so CSS classes control the size.
        self.assertNotIn('width="24"', svg)
        self.assertNotIn('height="24"', svg)

    def test_unknown_icon_fails_loudly(self):
        with self.assertRaises(TemplateSyntaxError):
            icon("not-a-real-icon")


class PartialTests(SimpleTestCase):
    def test_every_status_badge_has_a_word_and_an_icon(self):
        for status, label in STATUS_LABELS.items():
            html = render_to_string("core/partials/status_badge.html", {"status": status})
            self.assertIn(label, html)
            self.assertEqual(html.count("<svg"), 1, status)

    def test_level_meter_fills_one_step_per_level(self):
        for level, steps in (("full", 1), ("guided", 2), ("minimal", 3)):
            html = render_to_string("core/partials/level_meter.html", {"level": level})
            self.assertEqual(html.count("<span></span>"), steps, level)
            self.assertIn("Help level:", html)

    def test_field_hint_shows_issue_text_and_errors(self):
        html = render_to_string(
            "core/partials/field_hint.html", {"hint": "Add modifier 25.", "errors": ["Enter a date."]}
        )
        self.assertIn("Add modifier 25.", html)
        self.assertIn('role="alert"', html)

    def test_demo_banner_text(self):
        html = render_to_string("core/partials/demo_banner.html")
        self.assertIn("Demo data only. Do not enter real patient information.", html)


class DesignTokenTests(SimpleTestCase):
    def test_brand_tokens_are_in_the_tailwind_entry_and_master_file(self):
        css = (settings.BASE_DIR / "static" / "css" / "input.css").read_text().lower()
        master = (settings.BASE_DIR / "design-system" / "rung" / "MASTER.md").read_text().lower()
        for value in ("#41a9da", "#013055", "#176f9c", "#52c299", "#187a56", "#b45309", "#dc2626"):
            self.assertIn(value, css)
            self.assertIn(value, master)
