"""Shared test setup."""

from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import Profile, Role

PASSWORD = "demo-pass-1"
DEMO_TODAY = date(2026, 11, 16)

# demo_payer_rules.csv holds 19 rules (the PRD text says 20, but its table lists 19).
RULE_COUNT = 19


def make_user(username, role):
    user = get_user_model().objects.create_user(username, password=PASSWORD, first_name=username.title())
    if role:
        Profile.objects.create(user=user, role=role)
    return user


def seed():
    with mock.patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}):
        call_command("seed_demo", stdout=StringIO())


class RoleTestCase(TestCase):
    """One worker (maria) and one specialist (dan), with no claims."""

    @classmethod
    def setUpTestData(cls):
        cls.maria = make_user("maria", Role.WORKER)
        cls.dan = make_user("dan", Role.SPECIALIST)


@override_settings(DEMO_TODAY=DEMO_TODAY)
class SeededTestCase(TestCase):
    """The full demo data set from seed_demo, with maria signed in."""

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.maria = get_user_model().objects.get(username="maria")
        cls.dan = get_user_model().objects.get(username="dan")

    def setUp(self):
        self.client.force_login(self.maria)
