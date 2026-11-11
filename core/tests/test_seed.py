from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import CaseEntry, Category, Claim, PayerRule, Role, WorkStatus
from core.tests.base import PASSWORD, RULE_COUNT, seed


class SeedDemoTests(TestCase):
    def test_loads_claims_rules_and_users(self):
        seed()
        self.assertEqual(Claim.objects.count(), 30)
        self.assertEqual(PayerRule.objects.count(), RULE_COUNT)
        User = get_user_model()
        maria = User.objects.get(username="maria")
        dan = User.objects.get(username="dan")
        self.assertEqual(maria.profile.role, Role.WORKER)
        self.assertEqual(dan.profile.role, Role.SPECIALIST)
        self.assertTrue(maria.check_password(PASSWORD))
        self.assertEqual(Claim.objects.filter(assigned_to=maria).count(), 30)

    def test_can_run_twice_and_resets_the_demo(self):
        seed()
        claim = Claim.objects.get(claim_id="CLM-1001")
        claim.work_status = WorkStatus.SUBMITTED
        claim.save()
        CaseEntry.objects.create(title="t", category=Category.MODIFIERS, problem="p", fix="f")
        seed()
        self.assertEqual(Claim.objects.count(), 30)
        self.assertEqual(PayerRule.objects.count(), RULE_COUNT)
        self.assertEqual(get_user_model().objects.count(), 2)
        self.assertEqual(CaseEntry.objects.count(), 0)
        self.assertEqual(Claim.objects.get(claim_id="CLM-1001").work_status, WorkStatus.NEW)

    def test_claim_fields_are_typed_and_in_file_order(self):
        seed()
        claim = Claim.objects.get(claim_id="CLM-1012")
        self.assertEqual(claim.date_of_service, date(2026, 10, 23))
        self.assertEqual(claim.units_1, 1)
        self.assertEqual(claim.charge_2, Decimal("180.00"))
        self.assertEqual(claim.expected_action, "fix")
        denied = Claim.objects.get(claim_id="CLM-1029")
        self.assertEqual(denied.work_status, WorkStatus.DENIED)
        self.assertEqual(denied.denial_code, "CO-18")
        # CLM-1005 is loaded before CLM-1029, so only CLM-1029 can be the duplicate.
        self.assertLess(Claim.objects.get(claim_id="CLM-1005").pk, denied.pk)

    def test_filing_limits_load_as_numbers(self):
        seed()
        medicare = PayerRule.objects.get(payer_name="Medicare Part B", rule_type="filing_limit")
        self.assertEqual(medicare.filing_limit_days, 365)
        self.assertEqual(PayerRule.objects.filter(payer_name=PayerRule.ALL_PAYERS).count(), 3)

    def test_needs_demo_password(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("seed_demo", stdout=StringIO())
