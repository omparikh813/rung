"""Shared test setup."""

from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import Organization, OrganizationType, Profile, Role

PASSWORD = "demo-pass-1"
DEMO_TODAY = date(2026, 11, 16)

# Claims after seeding: 30 sample claims and Cassandra's 20 past claims at AGS Health, and 3 at Summit.
SEEDED_CLAIMS = 53

# demo_payer_rules.csv holds 19 rules (the PRD text says 20, but its table lists 19).
RULE_COUNT = 19


def test_organization(name="Test Billing Co"):
    organization, _ = Organization.objects.get_or_create(
        name=name, defaults={"org_type": OrganizationType.BILLING, "seat_limit": 10}
    )
    return organization


def make_user(username, role, organization=None):
    """A user with a role. They join the test organization unless another is given."""
    user = get_user_model().objects.create_user(username, password=PASSWORD, first_name=username.title())
    if role:
        Profile.objects.create(user=user, role=role, organization=organization or test_organization())
    return user


def seed():
    with mock.patch.dict("os.environ", {"DEMO_PASSWORD": PASSWORD}):
        call_command("seed_demo", stdout=StringIO())


class RoleTestCase(TestCase):
    """One worker (maria) and one specialist (dan) in a test organization, with no claims."""

    @classmethod
    def setUpTestData(cls):
        cls.maria = make_user("maria", Role.WORKER)
        cls.dan = make_user("dan", Role.SPECIALIST)


@override_settings(DEMO_TODAY=DEMO_TODAY)
class SeededTestCase(TestCase):
    """The full demo data set from seed_demo, with Flora (a worker at AGS Health) signed in.

    self.maria is Flora, who holds the sample claims, and self.dan is James, AGS Health's specialist.
    """

    @classmethod
    def setUpTestData(cls):
        seed()
        cls.maria = get_user_model().objects.get(username="flora")
        cls.dan = get_user_model().objects.get(username="james")
        cls.om = get_user_model().objects.get(username="om")
        cls.ags = Organization.objects.get(name="AGS Health")
        cls.summit = Organization.objects.get(name="Summit Medical Billing")

    def setUp(self):
        self.client.force_login(self.maria)
