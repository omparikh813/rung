from django.urls import reverse

from core import ai
from core.models import (
    AIReview,
    Attempt,
    CaseEntry,
    Category,
    Claim,
    ClaimEvent,
    EventAction,
    FinalAction,
    HelpRequest,
    Outcome,
    RequestStatus,
    Role,
    WorkStatus,
)
from core.tests.base import SeededTestCase, make_user
from core.tests.test_ai_client import ISSUE, NEEDS_FIX

QUESTION = "Is this an Annual Wellness Visit or a routine physical?"
ENTRY = {
    "res-save_to_library": "on",
    "res-title": "Routine physical billed to Medicare",
    "res-category": "code_matching",
    "res-payer_name": "Medicare Part B",
    "res-codes": "99397, Z00.00",
    "res-denial_code": "",
    "res-problem": "Medicare does not cover routine physicals.",
    "res-fix": "Add modifier GY so the patient or another plan can be billed.",
    "res-tip": "Check whether the visit meets Annual Wellness Visit rules first.",
}


class HelpTestCase(SeededTestCase):
    claim_id = "CLM-1021"

    def setUp(self):
        super().setUp()
        self.claim = Claim.objects.get(claim_id=self.claim_id)
        self.claim_url = reverse("claim", args=[self.claim.pk])

    def claim_data(self, **changes):
        claim = Claim.objects.get(pk=self.claim.pk)
        from core.forms import ClaimForm

        data = {k: "" if v is None else str(v) for k, v in ClaimForm(instance=claim).initial.items()}
        data.update(changes)
        return data

    def ask(self, question=QUESTION, **changes):
        return self.client.post(self.claim_url, self.claim_data(action="ask", question=question, **changes), follow=True)

    def open_request(self):
        self.ask()
        return HelpRequest.objects.get(claim=self.claim)

    def resolve(self, help_request, outcome=Outcome.SUBMITTED, note="Billed with GY.", entry=ENTRY, **changes):
        self.client.force_login(self.dan)
        data = self.claim_data(**{"res-outcome": outcome, "res-resolution_note": note, **(entry or {}), **changes})
        return self.client.post(reverse("help_detail", args=[help_request.pk]), data, follow=True)

    def refresh(self):
        self.claim = Claim.objects.get(pk=self.claim.pk)
        return self.claim


class AskSpecialistTests(HelpTestCase):
    def test_workspace_has_the_ask_dialog_with_a_question_box(self):
        response = self.client.get(self.claim_url)
        self.assertContains(response, 'id="ask-dialog"')
        self.assertContains(response, 'name="question"')
        self.assertContains(response, 'value="ask"')

    def test_asking_creates_a_request_and_sets_waiting(self):
        response = self.ask(modifiers_1="GA")
        self.assertRedirects(response, self.claim_url)
        self.assertContains(response, "Request sent. A specialist will pick it up.")
        self.assertContains(response, "Waiting on Specialist")
        request = HelpRequest.objects.get()
        self.assertEqual((request.claim, request.worker, request.question), (self.claim, self.maria, QUESTION))
        self.assertEqual(request.status, RequestStatus.OPEN)
        claim = self.refresh()
        self.assertEqual((claim.work_status, claim.help_request_open), (WorkStatus.WAITING, True))
        # The worker's unsaved changes are saved with the request.
        self.assertEqual(claim.modifiers_1, "GA")
        actions = list(ClaimEvent.objects.filter(claim=claim).order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, [EventAction.EDIT, EventAction.ESCALATE])
        self.assertEqual(ClaimEvent.objects.get(action=EventAction.ESCALATE).new_value, QUESTION)

    def test_question_is_required(self):
        response = self.ask(question="   ")
        self.assertContains(response, "Type a question for the specialist before sending.")
        self.assertEqual(HelpRequest.objects.count(), 0)
        self.assertEqual(self.refresh().work_status, WorkStatus.NEW)

    def test_asking_scores_the_claim_as_an_escalation(self):
        self.ask()
        attempt = Attempt.objects.get()
        # CLM-1021 expects an escalation, so asking is correct.
        self.assertEqual((attempt.action_taken, attempt.correct), (FinalAction.ESCALATE, True))
        self.assertTrue(self.refresh().scored)

    def test_escalating_a_fixable_claim_is_scored_incorrect_but_never_discouraged(self):
        self.claim = Claim.objects.get(claim_id="CLM-1012")
        self.claim_url = reverse("claim", args=[self.claim.pk])
        response = self.ask()
        self.assertFalse(Attempt.objects.get().correct)
        self.assertNotContains(response, "ncorrect")

    def test_waiting_claim_is_read_only_for_the_worker(self):
        self.ask()
        response = self.client.get(self.claim_url)
        self.assertFalse(response.context["editable"])
        self.assertContains(response, "This claim is with a specialist.")
        self.assertEqual(self.client.post(self.claim_url, self.claim_data(action="save")).status_code, 403)

    def test_sidebar_badge_counts_open_requests(self):
        self.assertNotContains(self.client.get(reverse("queue")), 'aria-label="1 open"')
        self.ask()
        self.assertContains(self.client.get(reverse("queue")), 'aria-label="1 open"')
        self.client.force_login(self.dan)
        self.assertContains(self.client.get(reverse("help_list")), 'aria-label="1 open"')


class HelpListTests(HelpTestCase):
    def test_worker_sees_own_requests_with_status_and_link(self):
        self.ask()
        other = make_user("other", Role.WORKER)
        HelpRequest.objects.create(claim=Claim.objects.get(claim_id="CLM-1001"), worker=other, question="Someone else's question")
        response = self.client.get(reverse("help_list"))
        self.assertTemplateUsed(response, "core/help_list.html")
        self.assertContains(response, QUESTION)
        self.assertContains(response, "CLM-1021")
        self.assertContains(response, f'href="{self.claim_url}"')
        self.assertContains(response, "Waiting on a specialist")
        self.assertNotContains(response, "Someone else's question")

    def test_worker_sees_the_specialists_note_once_resolved(self):
        self.resolve(self.open_request(), note="Billed with GY so the patient can be billed.")
        self.client.force_login(self.maria)
        response = self.client.get(reverse("help_list"))
        self.assertContains(response, "Resolved")
        self.assertContains(response, "Billed with GY so the patient can be billed.")
        self.assertContains(response, "Fixed and submitted")

    def test_request_created_by_maria_appears_for_dan(self):
        help_request = self.open_request()
        AIReview.objects.create(
            claim=self.claim, model="m", claim_version_hash="x",
            result_json=ai.clean_review({**NEEDS_FIX, "issues": [{**ISSUE, "category": "code_matching", "field": "cpt_1"}]}),
        )  # fmt: skip
        self.client.force_login(self.dan)
        self.assertRedirects(self.client.get(reverse("home")), reverse("help_list"))
        response = self.client.get(reverse("help_list"))
        self.assertTemplateUsed(response, "core/help_inbox.html")
        for text in ("CLM-1021", "Maria", "Medicare Part B", QUESTION, "Code matching", "minute"):
            self.assertContains(response, text)
        self.assertContains(response, reverse("help_detail", args=[help_request.pk]))

    def test_specialist_sees_all_requests_open_first(self):
        first = self.open_request()
        self.resolve(first, entry=None)
        other_claim = Claim.objects.get(claim_id="CLM-1009")
        newer_open = HelpRequest.objects.create(claim=other_claim, worker=self.maria, question="Newer open question")
        rows = self.client.get(reverse("help_list")).context["requests"]
        self.assertEqual([row["pk"] for row in rows], [newer_open.pk, first.pk])
        self.assertEqual(self.client.get(reverse("help_list")).context["open_count"], 1)

    def test_empty_states(self):
        self.assertContains(self.client.get(reverse("help_list")), "No help requests yet")
        self.client.force_login(self.dan)
        self.assertContains(self.client.get(reverse("help_list")), "No help requests")


class HelpDetailTests(HelpTestCase):
    def test_detail_shows_claim_question_review_and_resolution_form(self):
        help_request = self.open_request()
        AIReview.objects.create(claim=self.claim, model="m", claim_version_hash="x", result_json=ai.clean_review(NEEDS_FIX))
        self.client.force_login(self.dan)
        response = self.client.get(reverse("help_detail", args=[help_request.pk]))
        for text in (QUESTION, "Annual routine physical exam.", "Service Lines", "History", "asked a specialist", "Resolve this request", "Save to Case Library", "Closed: appeal sent", "Fixed and returned to worker"):
            self.assertContains(response, text)
        # The specialist always sees the full text of each issue, never a faded version.
        self.assertContains(response, ISSUE["full"])
        self.assertNotContains(response, "Show answer")
        self.assertTrue(response.context["editable"])

    def test_case_fields_are_filled_from_the_claim_without_patient_data(self):
        help_request = self.open_request()
        self.client.force_login(self.dan)
        initial = self.client.get(reverse("help_detail", args=[help_request.pk])).context["resolution"].initial
        self.assertEqual(initial["payer_name"], "Medicare Part B")
        self.assertEqual(initial["codes"], "99397, Z00.00")
        self.assertEqual(initial["denial_code"], "")
        filled = " ".join(str(value) for value in initial.values())
        for private in (self.claim.patient_first, self.claim.patient_last, self.claim.member_id, str(self.claim.patient_dob), str(self.claim.date_of_service)):
            self.assertNotIn(private, filled)

    def test_save_to_case_library_is_checked_by_default(self):
        help_request = self.open_request()
        self.client.force_login(self.dan)
        response = self.client.get(reverse("help_detail", args=[help_request.pk]))
        self.assertTrue(response.context["resolution"]["save_to_library"].value())
        self.assertContains(response, 'x-data="{ save: true }"')

    def test_resolving_updates_the_claim_and_creates_a_case_entry(self):
        help_request = self.open_request()
        response = self.resolve(help_request, modifiers_1="GY")
        self.assertRedirects(response, reverse("help_list"))
        self.assertContains(response, "Request for CLM-1021 resolved. The fix was saved to the Case Library.")
        claim = self.refresh()
        # A claim a specialist fixed and submitted is paid by the simulated payer.
        self.assertEqual((claim.work_status, claim.help_request_open, claim.modifiers_1), (WorkStatus.PAID, False, "GY"))
        help_request.refresh_from_db()
        self.assertEqual(help_request.status, RequestStatus.RESOLVED)
        self.assertEqual((help_request.specialist, help_request.outcome), (self.dan, Outcome.SUBMITTED))
        self.assertEqual(help_request.resolution_note, "Billed with GY.")
        self.assertIsNotNone(help_request.resolved_at)
        entry = CaseEntry.objects.get()
        self.assertEqual((entry.title, entry.category), ("Routine physical billed to Medicare", Category.CODE_MATCHING))
        self.assertEqual((entry.payer_name, entry.codes), ("Medicare Part B", "99397, Z00.00"))
        self.assertEqual((entry.created_by, entry.source_request), (self.dan, help_request))
        edit = ClaimEvent.objects.get(claim=claim, action=EventAction.EDIT)
        self.assertEqual((edit.field, edit.new_value, edit.user), ("modifiers_1", "GY", self.dan))
        done = ClaimEvent.objects.get(claim=claim, action=EventAction.RESOLVE)
        self.assertEqual((done.old_value, done.new_value, done.user), ("Fixed and submitted", "Billed with GY.", self.dan))

    def test_each_outcome_sets_the_claim_status(self):
        expected = {
            Outcome.RETURNED: WorkStatus.READY,
            Outcome.SUBMITTED: WorkStatus.PAID,
            Outcome.WRITE_OFF: WorkStatus.CLOSED,
            Outcome.APPEAL: WorkStatus.CLOSED,
        }
        for outcome, status in expected.items():
            HelpRequest.objects.all().delete()
            Claim.objects.filter(pk=self.claim.pk).update(work_status=WorkStatus.NEW)
            self.client.force_login(self.maria)
            self.resolve(self.open_request(), outcome=outcome, entry=None)
            self.assertEqual(self.refresh().work_status, status, outcome)

    def test_unchecked_box_saves_no_case_entry(self):
        response = self.resolve(self.open_request(), entry=None)
        self.assertContains(response, "Request for CLM-1021 resolved.")
        self.assertEqual(CaseEntry.objects.count(), 0)
        self.assertEqual(HelpRequest.objects.get().status, RequestStatus.RESOLVED)

    def test_note_is_required_and_entry_fields_are_required_when_the_box_is_checked(self):
        help_request = self.open_request()
        response = self.resolve(help_request, note="", entry={"res-save_to_library": "on", "res-tip": "only a tip"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Some fields need a fix before this can be resolved.")
        self.assertContains(response, "This field is required.")
        self.assertContains(response, "This field is needed to save the entry.", count=4)
        help_request.refresh_from_db()
        self.assertEqual(help_request.status, RequestStatus.OPEN)
        self.assertEqual(self.refresh().work_status, WorkStatus.WAITING)
        self.assertEqual(CaseEntry.objects.count(), 0)

    def test_returned_claim_is_back_in_the_workers_open_queue_and_not_scored_again(self):
        self.resolve(self.open_request(), outcome=Outcome.RETURNED, note="Fixed the code. Please submit.", entry=None)
        self.client.force_login(self.maria)
        open_ids = [claim.claim_id for claim in self.client.get(reverse("queue")).context["claims"]]
        self.assertIn("CLM-1021", open_ids)
        page = self.client.get(self.claim_url)
        self.assertTrue(page.context["editable"])
        self.assertContains(page, "Fixed the code. Please submit.")
        self.client.post(self.claim_url, self.claim_data(action="submit_confirmed"))
        self.assertEqual(self.refresh().work_status, WorkStatus.PAID)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_resolved_request_is_read_only(self):
        help_request = self.open_request()
        self.resolve(help_request, entry=None)
        response = self.client.get(reverse("help_detail", args=[help_request.pk]))
        self.assertFalse(response.context["editable"])
        self.assertContains(response, "Billed with GY.")
        self.assertNotContains(response, "Resolve request")
        self.assertEqual(self.resolve(help_request, entry=None).status_code, 403)

    def test_answer_key_is_not_on_the_specialist_page(self):
        help_request = self.open_request()
        self.client.force_login(self.dan)
        response = self.client.get(reverse("help_detail", args=[help_request.pk]))
        self.assertNotContains(response, Claim.objects.get(pk=self.claim.pk).expected_issue)
        self.assertNotContains(response, "expected_")


class HelpAccessTests(HelpTestCase):
    def test_worker_cannot_open_request_detail(self):
        help_request = self.open_request()
        self.assertEqual(self.client.get(reverse("help_detail", args=[help_request.pk])).status_code, 403)

    def test_specialist_reaches_a_claim_only_through_its_help_request(self):
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(self.claim_url).status_code, 403)
        self.assertEqual(self.client.get(reverse("claim_review", args=[self.claim.pk])).status_code, 403)
        self.client.force_login(self.maria)
        help_request = self.open_request()
        self.client.force_login(self.dan)
        self.assertRedirects(self.client.get(self.claim_url), reverse("help_detail", args=[help_request.pk]))

    def test_specialist_can_recheck_a_claim_in_a_help_request(self):
        from unittest import mock

        from core.tests.test_ai_client import API_KEY, READY, reply

        self.open_request()
        self.client.force_login(self.dan)
        with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": API_KEY}), mock.patch("core.ai.httpx.post") as post:
            post.return_value = reply(READY)
            response = self.client.post(reverse("claim_review", args=[self.claim.pk]), self.claim_data(modifiers_1="GY"))
        self.assertContains(response, "No issues found")
        claim = self.refresh()
        self.assertEqual(claim.modifiers_1, "GY")
        # A specialist's check never moves a waiting claim out of Waiting on Specialist.
        self.assertEqual(claim.work_status, WorkStatus.WAITING)
        self.assertEqual(ClaimEvent.objects.get(action=EventAction.EDIT).user, self.dan)
