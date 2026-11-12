from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import Attempt, CaseEntry, Category, Claim, HelpLevel, Organization, PayerRule, Role, SkillRecord, WorkStatus
from core.skills import passport
from core.tests.base import PASSWORD, RULE_COUNT, seed


class SeedDemoTests(TestCase):
    def test_loads_two_organizations_and_their_people(self):
        seed()
        ags = Organization.objects.get(name="AGS Health")
        summit = Organization.objects.get(name="Summit Medical Billing")
        self.assertEqual((ags.seat_limit, ags.directory_company, ags.claim_prefix), (10, "AGS Health", "CLM"))
        self.assertEqual(summit.claim_prefix, "SMB")
        roles = {p.user.username: (p.role, p.organization.name) for p in ags.members.select_related("user", "organization")}
        self.assertEqual(
            roles,
            {
                "om": (Role.ADMIN, "AGS Health"),
                "james": (Role.SPECIALIST, "AGS Health"),
                "flora": (Role.WORKER, "AGS Health"),
                "kevin": (Role.WORKER, "AGS Health"),
                "cassandra": (Role.WORKER, "AGS Health"),
            },
        )
        self.assertEqual({p.user.username: p.role for p in summit.members.all()}, {"steven": Role.ADMIN, "kaua": Role.WORKER})
        for user in get_user_model().objects.all():
            self.assertTrue(user.check_password(PASSWORD), user.username)
        self.assertEqual(ags.seats_used, 5)

    def test_claims_belong_to_the_right_organization(self):
        seed()
        flora = get_user_model().objects.get(username="flora")
        kaua = get_user_model().objects.get(username="kaua")
        self.assertEqual(Claim.objects.filter(assigned_to=flora, organization__name="AGS Health").count(), 30)
        self.assertEqual(
            list(Claim.objects.filter(assigned_to=kaua).values_list("claim_id", flat=True)), ["SMB-1001", "SMB-1002", "SMB-1003"]
        )
        self.assertEqual(Claim.objects.filter(assigned_to=kaua, organization__name="Summit Medical Billing").count(), 3)
        self.assertEqual(PayerRule.objects.count(), RULE_COUNT)

    def test_cassandra_is_ready_for_promotion(self):
        seed()
        cassandra = get_user_model().objects.get(username="cassandra")
        self.assertEqual(Claim.objects.filter(assigned_to=cassandra).count(), 20)
        self.assertEqual(Attempt.objects.filter(worker=cassandra).count(), 20)
        self.assertEqual(SkillRecord.objects.filter(worker=cassandra, help_level=HelpLevel.MINIMAL).count(), 4)
        data = passport(cassandra)
        self.assertEqual(data["accuracy"], 90)
        self.assertTrue(data["ready"])
        # Her past patients never match the sample claims' patients.
        sample = set(Claim.objects.filter(assigned_to__username="flora").values_list("patient_last", flat=True))
        history = set(Claim.objects.filter(assigned_to=cassandra).values_list("patient_last", flat=True))
        self.assertFalse(sample & history)
        self.assertFalse(passport(get_user_model().objects.get(username="flora"))["ready"])

    def test_can_run_twice_and_resets_the_demo(self):
        seed()
        claim = Claim.objects.get(claim_id="CLM-1001")
        claim.work_status = WorkStatus.SUBMITTED
        claim.save()
        CaseEntry.objects.create(title="t", category=Category.MODIFIERS, problem="p", fix="f")
        seed()
        self.assertEqual(Claim.objects.count(), 53)
        self.assertEqual(PayerRule.objects.count(), RULE_COUNT)
        self.assertEqual(get_user_model().objects.count(), 7)
        self.assertEqual(Organization.objects.count(), 2)
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
