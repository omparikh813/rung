from django.urls import reverse

from core import ai, payer
from core.forms import ClaimForm
from core.models import AIReview, Attempt, Claim, ClaimEvent, ClaimStatus, EventAction, HelpRequest, RequestStatus, WorkStatus
from core.tests.base import SeededTestCase
from core.tests.test_ai_client import ISSUE, NEEDS_FIX, READY


class PayerTestCase(SeededTestCase):
    def claim(self, claim_id):
        return Claim.objects.get(claim_id=claim_id)

    def submit(self, claim_id, **changes):
        """Submit through the workspace, past the confirmation dialog."""
        claim = self.claim(claim_id)
        data = {k: "" if v is None else str(v) for k, v in ClaimForm(instance=claim).initial.items()}
        data.update(changes, action="submit_confirmed")
        return self.client.post(reverse("claim", args=[claim.pk]), data, follow=True)

    def without_answer_key(self, claim_id):
        Claim.objects.filter(claim_id=claim_id).update(expected_action="", expected_category="", expected_field="", expected_value="")
        return self.claim(claim_id)

    def review(self, claim, result):
        return AIReview.objects.create(claim=claim, result_json=ai.clean_review(result), model="m", claim_version_hash=ai.claim_version_hash(claim))


class AnswerKeyJudgeTests(PayerTestCase):
    def test_clean_claim_is_paid_at_once(self):
        response = self.submit("CLM-1001")
        self.assertContains(response, "CLM-1001 submitted. The payer paid it.")
        claim = self.claim("CLM-1001")
        self.assertEqual(claim.work_status, WorkStatus.PAID)
        event = ClaimEvent.objects.get(claim=claim, action=EventAction.PAYER)
        self.assertEqual((event.new_value, event.user), ("Paid", None))
        self.assertIn("CLM-1001", [c.claim_id for c in self.client.get(reverse("queue"), {"tab": "done"}).context["claims"]])

    def test_correct_fix_is_paid(self):
        self.submit("CLM-1012", modifiers_1="25")
        self.assertEqual(self.claim("CLM-1012").work_status, WorkStatus.PAID)

    def test_wrong_submission_is_denied_with_the_categorys_code_and_returns_to_the_queue(self):
        response = self.submit("CLM-1012")
        self.assertContains(response, "CLM-1012 was denied by the payer (CO-4). It is back in your queue to fix.")
        claim = self.claim("CLM-1012")
        self.assertEqual((claim.work_status, claim.status), (WorkStatus.DENIED, ClaimStatus.DENIED))
        self.assertEqual(claim.denial_code, "CO-4")
        self.assertIn("modifier", claim.denial_reason)
        self.assertIn("CLM-1012", [c.claim_id for c in self.client.get(reverse("queue")).context["claims"]])
        page = self.client.get(reverse("claim", args=[claim.pk]))
        self.assertContains(page, "Denied by the payer")
        self.assertContains(page, "CO-4")
        self.assertTrue(page.context["editable"])
        self.assertContains(page, "answered the claim. Denied: CO-4")

    def test_denied_claim_can_be_fixed_and_resubmitted_but_is_scored_once(self):
        self.submit("CLM-1012")
        self.submit("CLM-1012", modifiers_1="25")
        self.assertEqual(self.claim("CLM-1012").work_status, WorkStatus.PAID)
        attempt = Attempt.objects.get(claim__claim_id="CLM-1012")
        self.assertFalse(attempt.correct)
        self.assertEqual(ClaimEvent.objects.filter(action=EventAction.PAYER).count(), 2)

    def test_each_category_has_its_own_denial_code(self):
        expected = {"CLM-1011": "CO-197", "CLM-1019": "CO-11", "CLM-1024": "CO-31", "CLM-1025": "CO-16", "CLM-1030": "CO-16"}
        for claim_id, code in expected.items():
            self.submit(claim_id)
            self.assertEqual(self.claim(claim_id).denial_code, code, claim_id)

    def test_late_and_duplicate_claims_get_their_own_codes(self):
        self.submit("CLM-1028")
        self.assertEqual(self.claim("CLM-1028").denial_code, "CO-29")
        self.submit("CLM-1029")
        self.assertEqual(self.claim("CLM-1029").denial_code, "CO-18")

    def test_claim_denied_before_keeps_its_denial_if_resubmitted_unfixed(self):
        self.submit("CLM-1010")
        claim = self.claim("CLM-1010")
        self.assertEqual((claim.work_status, claim.denial_code), (WorkStatus.DENIED, "CO-197"))

    def test_claim_a_specialist_resolved_is_paid(self):
        claim = self.claim("CLM-1021")
        HelpRequest.objects.create(claim=claim, worker=self.maria, question="?", status=RequestStatus.RESOLVED)
        self.submit("CLM-1021")
        self.assertEqual(self.claim("CLM-1021").work_status, WorkStatus.PAID)

    def test_submitting_a_claim_that_needed_a_specialist_is_denied(self):
        self.submit("CLM-1021")
        self.assertEqual(self.claim("CLM-1021").work_status, WorkStatus.DENIED)


class AIJudgeTests(PayerTestCase):
    """A claim with no answer key is judged by its latest AI review."""

    def test_no_open_issues_means_paid(self):
        claim = self.without_answer_key("CLM-1001")
        self.review(claim, READY)
        self.submit("CLM-1001")
        self.assertEqual(self.claim("CLM-1001").work_status, WorkStatus.PAID)

    def test_open_issue_means_denied_with_that_issues_category(self):
        claim = self.without_answer_key("CLM-1012")
        self.review(claim, NEEDS_FIX)
        self.submit("CLM-1012")
        claim = self.claim("CLM-1012")
        self.assertEqual((claim.work_status, claim.denial_code), (WorkStatus.DENIED, "CO-4"))

    def test_issue_whose_field_was_changed_no_longer_blocks_payment(self):
        claim = self.without_answer_key("CLM-1012")
        self.review(claim, NEEDS_FIX)
        self.submit("CLM-1012", modifiers_1="25")
        self.assertEqual(self.claim("CLM-1012").work_status, WorkStatus.PAID)

    def test_low_confidence_issue_still_counts_as_open(self):
        claim = self.without_answer_key("CLM-1012")
        self.review(claim, {**NEEDS_FIX, "issues": [{**ISSUE, "confidence": "low"}]})
        self.submit("CLM-1012")
        self.assertEqual(self.claim("CLM-1012").work_status, WorkStatus.DENIED)

    def test_nothing_to_judge_by_leaves_the_claim_submitted(self):
        self.without_answer_key("CLM-1001")
        response = self.submit("CLM-1001")
        self.assertContains(response, "CLM-1001 submitted.")
        self.assertEqual(self.claim("CLM-1001").work_status, WorkStatus.SUBMITTED)
        self.assertEqual(payer.respond(self.claim("CLM-1001"), self.maria), "")
        self.assertFalse(ClaimEvent.objects.filter(action=EventAction.PAYER).exists())

    def test_claims_without_an_answer_key_are_still_not_scored(self):
        claim = self.without_answer_key("CLM-1001")
        self.review(claim, READY)
        self.submit("CLM-1001")
        self.assertEqual(Attempt.objects.count(), 0)


class PaidStatusTests(PayerTestCase):
    def test_paid_claim_is_read_only_and_shows_a_paid_badge(self):
        self.submit("CLM-1001")
        page = self.client.get(reverse("claim", args=[self.claim("CLM-1001").pk]))
        self.assertFalse(page.context["editable"])
        self.assertContains(page, "The payer paid this claim.")
        self.assertContains(page, "Paid")
        self.assertContains(page, "answered the claim. Paid.")

    def test_the_answer_key_text_is_not_shown_with_the_verdict(self):
        response = self.submit("CLM-1012")
        self.assertNotContains(response, self.claim("CLM-1012").expected_issue)


class InsurerLibraryEntryTests(PayerTestCase):
    """A claim the insurer denied, then paid once fixed, becomes a Case Library entry."""

    def entry(self):
        from core.models import CaseEntry

        return CaseEntry.objects.get(from_insurer=True)

    def test_denied_then_fixed_and_paid_writes_an_entry(self):
        self.submit("CLM-1012")
        response = self.submit("CLM-1012", modifiers_1="25")
        self.assertContains(response, "CLM-1012 submitted. The payer paid it, and the fix was added to the Case Library.")
        entry = self.entry()
        self.assertEqual(entry.title, "Modifiers: Summit Health PPO denial CO-4")
        self.assertEqual((entry.category, entry.payer_name, entry.denial_code), ("modifiers", "Summit Health PPO", "CO-4"))
        self.assertEqual(entry.codes, "99213, 20610, M17.11, I10")
        self.assertIn("Summit Health PPO denied the claim with CO-4:", entry.problem)
        self.assertEqual(entry.fix, "Modifiers (line 1) changed to 25. The claim was resubmitted and the insurer paid it.")
        self.assertEqual(entry.tip, "Check Modifiers (line 1) before the first submission to avoid a CO-4 denial.")
        self.assertEqual((entry.created_by, entry.source_claim.claim_id), (None, "CLM-1012"))

    def test_paid_on_the_first_try_writes_nothing(self):
        from core.models import CaseEntry

        self.submit("CLM-1001")
        self.submit("CLM-1013", modifiers_1="GP")
        self.assertEqual(CaseEntry.objects.count(), 0)

    def test_still_denied_writes_nothing(self):
        from core.models import CaseEntry

        self.submit("CLM-1012")
        self.submit("CLM-1012", modifiers_1="59")
        self.assertEqual(CaseEntry.objects.count(), 0)

    def test_a_claim_that_arrived_denied_counts_too(self):
        self.submit("CLM-1010", prior_auth_number="SH4471932")
        entry = self.entry()
        self.assertEqual((entry.category, entry.denial_code), ("prior_auth", "CO-197"))
        self.assertIn("Prior auth number was added.", entry.fix)
        self.assertNotIn("SH4471932", entry.fix + entry.tip + entry.problem)

    def test_patient_details_never_reach_the_entry(self):
        claim = self.claim("CLM-1022")
        self.submit("CLM-1022", payer_name="Crestline Insurance PPO", member_id="CRX20093357")
        entry = self.entry()
        self.assertIn("Payer changed to Crestline Insurance PPO.", entry.fix)
        self.assertIn("Member ID was corrected.", entry.fix)
        text = " ".join([entry.title, entry.problem, entry.fix, entry.tip, entry.codes])
        for private in ("CRX20093357", claim.member_id, claim.patient_first, claim.patient_last, str(claim.patient_dob), str(claim.date_of_service)):
            self.assertNotIn(private, text)

    def test_only_changes_since_the_first_denial_are_listed(self):
        self.submit("CLM-1012", units_2="1", charge_1="150.00", icd10_secondary="I10")
        self.submit("CLM-1012", modifiers_2="RT", units_1="1")
        self.submit("CLM-1012", modifiers_1="25")
        self.assertEqual(self.entry().fix, "Modifiers (line 1) changed to 25. The claim was resubmitted and the insurer paid it.")

    def test_entry_shows_its_source_and_specialists_can_tidy_it(self):
        self.submit("CLM-1012")
        self.submit("CLM-1012", modifiers_1="25")
        entry = self.entry()
        self.assertContains(self.client.get(reverse("library")), "From the simulated insurer")
        detail = self.client.get(reverse("library_detail", args=[entry.pk]))
        self.assertContains(detail, "Written automatically from the simulated insurer")
        self.assertFalse(detail.context["can_change"])
        self.client.force_login(self.dan)
        self.assertTrue(self.client.get(reverse("library_detail", args=[entry.pk])).context["can_change"])
        self.assertEqual(self.client.get(reverse("library_edit", args=[entry.pk])).status_code, 200)

    def test_the_entry_shows_as_a_similar_case_on_a_related_claim(self):
        self.submit("CLM-1012")
        self.submit("CLM-1012", modifiers_1="25")
        page = self.client.get(reverse("claim", args=[self.claim("CLM-1001").pk]))
        self.assertContains(page, "Modifiers: Summit Health PPO denial CO-4")

    def test_no_second_entry_when_a_specialist_already_wrote_one_up(self):
        from core.models import CaseEntry

        claim = self.claim("CLM-1026")  # arrived denied with CO-16
        request = HelpRequest.objects.create(claim=claim, worker=self.maria, question="?", status=RequestStatus.RESOLVED)
        self.submit("CLM-1026", attachments="wound measurements")
        self.assertEqual(self.claim("CLM-1026").work_status, WorkStatus.PAID)
        # Without a specialist write-up the insurer entry is created...
        self.assertEqual(CaseEntry.objects.filter(from_insurer=True).count(), 1)
        CaseEntry.objects.all().delete()
        # ...but with one, it is not repeated.
        CaseEntry.objects.create(title="t", category="documentation", problem="p", fix="f", source_request=request, created_by=self.dan)
        Claim.objects.filter(pk=claim.pk).update(work_status=WorkStatus.DENIED)
        self.submit("CLM-1026", attachments="wound measurements and depth")
        self.assertEqual(self.claim("CLM-1026").work_status, WorkStatus.PAID)
        self.assertEqual(CaseEntry.objects.filter(from_insurer=True).count(), 0)
