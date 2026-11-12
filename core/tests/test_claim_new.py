from django.urls import reverse

from core.claims import ANSWER_KEY_FIELDS, next_claim_id
from core.models import Claim, WorkStatus
from core.tests.base import SEEDED_CLAIMS, SeededTestCase

URL = reverse("claim_new")
GOOD = {
    "patient_first": "Pat", "patient_last": "Lee", "patient_dob": "1980-02-03", "patient_sex": "F",
    "payer_name": "Summit Health PPO", "member_id": "SHP100200300", "date_of_service": "2026-11-05",
    "cpt_1": "99213", "units_1": "1", "charge_1": "150.00", "icd10_primary": "I10",
    "rendering_provider": "Dr. Lena Ortiz (Family Medicine)", "clinical_note": "Hypertension follow up. 15 min.",
}  # fmt: skip


class NewClaimTests(SeededTestCase):
    def test_form_page_has_the_claim_fields_and_no_answer_key(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        for text in ("Create a claim", "Patient and Coverage", "Service Lines", "Clinical note", "Choose a payer", "Required"):
            self.assertContains(response, text)
        fields = set(response.context["form"].fields)
        self.assertFalse(fields & set(ANSWER_KEY_FIELDS))
        self.assertNotIn("claim_id", fields)
        self.assertNotContains(response, "expected_")

    def test_creating_a_claim_assigns_it_and_opens_the_workspace(self):
        response = self.client.post(URL, GOOD, follow=True)
        claim = Claim.objects.get(patient_last="Lee")
        self.assertRedirects(response, reverse("claim", args=[claim.pk]))
        self.assertContains(response, "CLM-1031 created. RUNG is checking it now.")
        self.assertEqual((claim.claim_id, claim.assigned_to, claim.work_status), ("CLM-1031", self.maria, WorkStatus.NEW))
        self.assertEqual((claim.payer_name, claim.cpt_1, claim.clinical_note), ("Summit Health PPO", "99213", GOOD["clinical_note"]))
        # The new claim is reviewed on first open, and it has no answer key.
        self.assertTrue(response.context["auto_review"])
        self.assertEqual(claim.expected_action, "")
        self.assertIn("CLM-1031", [c.claim_id for c in self.client.get(reverse("queue")).context["claims"]])

    def test_claim_ids_count_up_from_the_highest_in_use(self):
        self.assertEqual(next_claim_id(self.ags), "CLM-1031")
        self.assertEqual(next_claim_id(self.summit), "SMB-1004")
        self.client.post(URL, GOOD)
        self.client.post(URL, {**GOOD, "patient_last": "Kim"})
        self.assertEqual(Claim.objects.get(patient_last="Kim").claim_id, "CLM-1032")

    def test_missing_required_fields_show_errors_and_create_nothing(self):
        response = self.client.post(URL, {**GOOD, "patient_last": "", "payer_name": "", "date_of_service": "", "cpt_1": "", "icd10_primary": ""})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.", count=5)
        self.assertContains(response, "Some fields need a fix before the claim can be created.")
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS)

    def test_answer_key_and_status_cannot_be_posted(self):
        self.client.post(URL, {**GOOD, "expected_action": "submit", "work_status": "paid", "claim_id": "CLM-9", "scored": "on"})
        claim = Claim.objects.get(patient_last="Lee")
        self.assertEqual((claim.expected_action, claim.work_status, claim.claim_id, claim.scored), ("", WorkStatus.NEW, "CLM-1031", False))

    def test_unknown_payer_is_rejected(self):
        response = self.client.post(URL, {**GOOD, "payer_name": "Acme Health"})
        self.assertContains(response, "Select a valid choice.")
        self.assertEqual(Claim.objects.count(), SEEDED_CLAIMS)

    def test_specialists_and_admins_can_create_their_own_claims(self):
        for user, last in ((self.dan, "Specialist"), (self.om, "Admin")):
            self.client.force_login(user)
            self.assertEqual(self.client.get(URL).status_code, 200)
            self.client.post(URL, {**GOOD, "patient_last": last})
            claim = Claim.objects.get(patient_last=last)
            self.assertEqual((claim.assigned_to, claim.organization), (user, self.ags))

    def test_create_a_claim_is_the_main_option_and_csv_is_secondary(self):
        page = self.client.get(reverse("upload"))
        self.assertContains(page, "Or upload a CSV file")
        self.assertContains(page, f'href="{URL}"')
        self.assertLess(page.content.decode().index("Create a claim"), page.content.decode().index("Or upload a CSV file"))
        self.assertContains(page, f'href="{URL}"', count=1)
        self.assertContains(self.client.get(reverse("queue")), f'href="{URL}"')
