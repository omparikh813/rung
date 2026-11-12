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
