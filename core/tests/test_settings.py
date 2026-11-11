from datetime import date

from django.conf import settings
from django.test import SimpleTestCase


class SettingsTests(SimpleTestCase):
    def test_demo_today_is_a_date(self):
        self.assertIsInstance(settings.DEMO_TODAY, date)

    def test_model_comes_from_settings(self):
        self.assertTrue(settings.RUNG_MODEL)

    def test_ready_thresholds_are_set(self):
        self.assertEqual(settings.RUNG_STREAK_TO_LOWER_HELP, 3)
        self.assertEqual(settings.RUNG_READY_MIN_SCORED, 20)
        self.assertEqual(settings.RUNG_READY_MIN_ACCURACY, 85)
        self.assertEqual(settings.RUNG_READY_MIN_MINIMAL, 4)
