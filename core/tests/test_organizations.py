"""Each organization's claims, requests, cases, and people are confidential to that organization."""

import json

from django.contrib.auth import get_user_model
from django.urls import reverse

from core import ai, payer
from core.claims import similar_cases
from core.models import CaseEntry, Category, Claim, ClaimEvent, EventAction, HelpRequest, Role
from core.organizations import DIRECTORY, organization_of, tier_for
from core.tests.base import SeededTestCase, make_user


class OrganizationTestCase(SeededTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.leo = User.objects.get(username="leo")
        self.nina = User.objects.get(username="nina")
        self.summit_claim = Claim.objects.get(claim_id="SMB-1002")
        self.ags_claim = Claim.objects.get(claim_id="CLM-1012")


class DirectoryAndTierTests(OrganizationTestCase):
    def test_directory_has_the_twenty_suggested_companies(self):
        self.assertEqual(len(DIRECTORY), 20)
        self.assertEqual(DIRECTORY[0], "XIFIN")
        self.assertIn("AGS Health", DIRECTORY)

    def test_tiers_follow_the_seat_ranges(self):
        self.assertEqual(tier_for(5), ("Starter", "Basic"))
        self.assertEqual(tier_for(10), ("Small Business", "Team"))
        self.assertEqual(tier_for(21), ("Growth", "Professional"))
        self.assertEqual(tier_for(800), ("Corporate", "Negotiated contract"))

    def test_seats(self):
        self.assertEqual((self.ags.seat_limit, self.ags.seats_used, self.ags.seats_left), (10, 5, 5))
        self.maria.is_active = False
        self.maria.save()
        self.assertEqual(self.ags.seats_used, 4)


class SeparationTests(OrganizationTestCase):
    def test_each_worker_sees_only_their_own_claims(self):
        self.client.force_login(self.leo)
        ids = [claim.claim_id for claim in self.client.get(reverse("queue")).context["claims"]]
        self.assertEqual(sorted(ids), ["SMB-1001", "SMB-1002", "SMB-1003"])
        self.assertEqual(self.client.get(reverse("claim", args=[self.ags_claim.pk])).status_code, 403)
        self.client.force_login(self.maria)
        self.assertEqual(self.client.get(reverse("claim", args=[self.summit_claim.pk])).status_code, 403)

    def test_a_specialist_cannot_reach_another_companys_requests_or_claims(self):
        request = HelpRequest.objects.create(claim=self.summit_claim, worker=self.leo, question="Summit question")
        self.client.force_login(self.dan)
        inbox = self.client.get(reverse("help_list"))
        self.assertNotContains(inbox, "Summit question")
        self.assertEqual(self.client.get(reverse("help_detail", args=[request.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("claim", args=[self.summit_claim.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("claim_review", args=[self.summit_claim.pk])).status_code, 404)
        self.assertNotContains(inbox, 'aria-label="1 open"')
        # Summit's own admin sees it.
        self.client.force_login(self.nina)
        self.assertContains(self.client.get(reverse("help_list")), "Summit question")

    def test_case_library_is_separate(self):
        summit_entry = CaseEntry.objects.create(
            title="Summit only fix", category=Category.MODIFIERS, codes="99213", problem="p", fix="f", organization=self.summit
        )
        self.assertEqual(similar_cases(self.ags_claim), [])
        self.assertEqual(similar_cases(self.summit_claim), [summit_entry])
        self.client.force_login(self.maria)
        self.assertNotContains(self.client.get(reverse("library")), "Summit only fix")
        self.assertEqual(self.client.get(reverse("library_detail", args=[summit_entry.pk])).status_code, 404)
        self.client.force_login(self.leo)
        self.assertContains(self.client.get(reverse("library")), "Summit only fix")

    def test_skill_passports_are_separate(self):
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(reverse("passport_user", args=["leo"])).status_code, 404)
        picker = [person.username for person in self.client.get(reverse("passport_user", args=["flora"])).context["workers"]]
        self.assertEqual(picker, ["cassandra", "flora", "kevin"])

    def test_export_is_separate(self):
        ClaimEvent.objects.create(claim=self.summit_claim, user=self.leo, action=EventAction.SUBMIT)
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(reverse("claim_export", args=[self.summit_claim.pk])).status_code, 404)

    def test_the_ai_never_sees_another_companys_patients(self):
        twin = Claim.objects.create(
            claim_id="SMB-1099", organization=self.summit, assigned_to=self.leo, patient_first="Patricia",
            patient_last="Nguyen", patient_dob=self.ags_claim.patient_dob, payer_name="Summit Health PPO",
            date_of_service=self.ags_claim.date_of_service, icd10_primary="I10", cpt_1="99213",
        )  # fmt: skip
        later = Claim.objects.create(
            claim_id="CLM-1099", organization=self.ags, assigned_to=self.maria, patient_first="Patricia",
            patient_last="Nguyen", patient_dob=self.ags_claim.patient_dob, payer_name="Summit Health PPO",
            date_of_service=self.ags_claim.date_of_service, icd10_primary="I10", cpt_1="99213",
        )  # fmt: skip
        earlier = json.loads(ai.patient_claims_block(later))
        self.assertEqual([row["claim_id"] for row in earlier], ["CLM-1012"])
        self.assertNotIn("SMB-1099", ai.patient_claims_block(later))
        self.assertFalse(payer.has_earlier_duplicate(twin))

    def test_new_and_uploaded_claims_join_the_uploaders_organization(self):
        self.client.force_login(self.leo)
        self.client.post(
            reverse("claim_new"),
            {"patient_first": "A", "patient_last": "B", "payer_name": "Summit Health PPO", "date_of_service": "2026-11-05", "cpt_1": "99213", "icd10_primary": "I10"},
        )  # fmt: skip
        claim = Claim.objects.get(patient_last="B")
        self.assertEqual((claim.claim_id, claim.organization, claim.assigned_to), ("SMB-1004", self.summit, self.leo))

    def test_a_user_without_an_organization_is_turned_away(self):
        loner = make_user("loner", Role.WORKER)
        loner.profile.organization = None
        loner.profile.save()
        self.client.force_login(loner)
        self.assertEqual(self.client.get(reverse("queue")).status_code, 403)
        self.assertIsNone(organization_of(loner))


class SignInTests(OrganizationTestCase):
    def sign_in(self, organization, username):
        from core.tests.base import PASSWORD

        return self.client.post(reverse("login"), {"organization": organization.pk, "username": username, "password": PASSWORD})

    def test_both_demo_organizations_are_listed(self):
        self.client.logout()
        response = self.client.get(reverse("login"))
        self.assertContains(response, ">AGS Health<")
        self.assertContains(response, ">Summit Medical Billing<")

    def test_each_person_signs_in_to_their_own_organization(self):
        self.client.logout()
        self.assertRedirects(self.sign_in(self.ags, "om"), reverse("home"), fetch_redirect_response=False)
        self.client.logout()
        self.assertRedirects(self.sign_in(self.summit, "leo"), reverse("home"), fetch_redirect_response=False)

    def test_signing_in_to_the_wrong_organization_fails(self):
        self.client.logout()
        response = self.sign_in(self.summit, "flora")
        self.assertContains(response, "That organization, username, or password is not right.")
        self.assertNotIn("_auth_user_id", self.client.session)
