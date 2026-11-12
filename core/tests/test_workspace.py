import json
from unittest import mock

from django.test import override_settings
from django.urls import NoReverseMatch, reverse

from core import ai
from core.claims import ANSWER_KEY_FIELDS
from core.models import AIReview, Category, Claim, ClaimEvent, EventAction, HelpLevel, SkillRecord, WorkStatus
from core.tests.base import SeededTestCase, make_user
from core.reviews import plain_fields
from core.tests.test_ai_client import API_KEY, ISSUE, NEEDS_FIX, READY, api_error, reply

# The issue text as a worker sees it, with form labels in place of field names.
SHOWN = {key: plain_fields(ISSUE[key]) for key in ("full", "guided", "minimal", "answer")}


class WorkspaceTestCase(SeededTestCase):
    claim_id = "CLM-1012"

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": API_KEY}))
        self.claim = Claim.objects.get(claim_id=self.claim_id)
        self.url = reverse("claim", args=[self.claim.pk])
        self.review_url = reverse("claim_review", args=[self.claim.pk])

    def form_data(self, **changes):
        """The claim form as the browser would post it, with some fields changed."""
        data = {}
        for name, value in self.client.get(self.url).context["form"].initial.items():
            data[name] = "" if value is None else str(value)
        data.update(changes)
        return data

    def review(self, result=NEEDS_FIX):
        """Store a review as if the AI had returned this result."""
        return AIReview.objects.create(
            claim=self.claim, result_json=ai.clean_review(result), model="m",
            claim_version_hash=ai.claim_version_hash(self.claim),
        )  # fmt: skip

    def refresh(self):
        self.claim = Claim.objects.get(pk=self.claim.pk)
        return self.claim


class OpenClaimTests(WorkspaceTestCase):
    def test_queue_rows_link_to_the_workspace(self):
        self.assertContains(self.client.get(reverse("queue")), f'href="{self.url}"')

    def test_first_open_asks_for_a_review_automatically(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context["auto_review"])
        self.assertContains(response, f'hx-get="{self.review_url}"')
        self.assertContains(response, 'hx-trigger="load"')
        self.assertContains(response, "Checking claim...")

    @mock.patch("core.ai.httpx.post")
    def test_review_is_stored_and_claim_becomes_needs_fix(self, post):
        post.return_value = reply(NEEDS_FIX)
        response = self.client.get(self.review_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AIReview.objects.filter(claim=self.claim).count(), 1)
        self.assertEqual(self.refresh().work_status, WorkStatus.NEEDS_FIX)
        event = ClaimEvent.objects.get(claim=self.claim, action=EventAction.CHECK)
        self.assertEqual(event.new_value, "1 issue found")
        self.assertEqual(event.user, self.maria)
        # The panel, the status badge, the field hint, and the history all update.
        self.assertContains(response, SHOWN["full"])
        self.assertContains(response, 'id="claim-status" hx-swap-oob="true"')
        self.assertContains(response, 'id="hint-modifiers_1" hx-swap-oob="true"')
        self.assertContains(response, "ran the AI review")

    @mock.patch("core.ai.httpx.post")
    def test_clean_claim_becomes_ready(self, post):
        post.return_value = reply(READY)
        response = self.client.get(self.review_url)
        self.assertEqual(self.refresh().work_status, WorkStatus.READY)
        self.assertContains(response, "No issues found. This claim is ready to submit.")

    @mock.patch("core.ai.httpx.post")
    def test_opening_again_reuses_the_review(self, post):
        post.return_value = reply(NEEDS_FIX)
        self.client.get(self.review_url)
        response = self.client.get(self.url)
        self.assertFalse(response.context["auto_review"])
        self.assertContains(response, SHOWN["full"])
        self.client.get(self.review_url)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(ClaimEvent.objects.filter(claim=self.claim, action=EventAction.CHECK).count(), 1)

    @mock.patch("core.ai.httpx.post")
    def test_api_error_shows_try_again_and_never_crashes(self, post):
        post.return_value = api_error(503)
        with self.assertLogs("core.ai", "WARNING"):
            response = self.client.get(self.review_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "RUNG could not check this claim just now.")
        self.assertContains(response, "Try again")
        self.assertContains(response, f'hx-get="{self.review_url}"')
        self.assertNotContains(response, API_KEY)
        self.assertEqual(self.refresh().work_status, WorkStatus.NEW)
        # Try again works once the API is back.
        post.return_value = reply(READY)
        self.assertContains(self.client.get(self.review_url), "No issues found")

    @override_settings(DEBUG=True)
    def test_missing_key_gets_a_setup_note_in_debug(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertLogs("core.ai", "WARNING"):
            response = self.client.get(self.review_url)
        self.assertContains(response, "OPENROUTER_API_KEY is not set in .env.")

    def test_denied_claim_shows_denial_code_and_reason(self):
        denied = Claim.objects.get(claim_id="CLM-1010")
        response = self.client.get(reverse("claim", args=[denied.pk]))
        self.assertContains(response, "CO-197")
        self.assertContains(response, "Precertification/authorization absent")
        self.assertNotContains(self.client.get(self.url), "Denied by the payer")

    def test_page_has_note_five_groups_and_history(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Right knee joint injection performed same visit.")
        for title in ("Patient and Coverage", "Provider", "Service Lines", "Diagnoses", "Authorization and Documents", "History"):
            self.assertContains(response, title)
        self.assertContains(response, "Demo data only. Do not enter real patient information.")


class FullHelpTests(WorkspaceTestCase):
    """Real claims always get full help, whatever the worker's level. Fading help is for Daily Training."""

    def test_full_text_fix_and_flagged_field(self):
        self.review()
        response = self.client.get(self.url)
        self.assertContains(response, SHOWN["full"], count=2)  # the card and under the field
        self.assertContains(response, "Suggested value")
        self.assertNotContains(response, "Show answer")
        self.assertEqual(response.context["groups"][2]["fields"][2]["hint"], SHOWN["full"])

    def test_a_worker_at_minimal_still_gets_full_help(self):
        for level in (HelpLevel.GUIDED, HelpLevel.MINIMAL):
            SkillRecord.objects.update_or_create(worker=self.maria, category=Category.MODIFIERS, defaults={"help_level": level})
            AIReview.objects.all().delete()
            self.review()
            response = self.client.get(self.url)
            self.assertContains(response, SHOWN["full"])
            self.assertNotContains(response, SHOWN["guided"])
            self.assertNotContains(response, "Show answer")

    def test_show_answer_no_longer_exists(self):
        with self.assertRaises(NoReverseMatch):
            reverse("claim_answer", args=[self.claim.pk, 0])


class SaveTests(WorkspaceTestCase):
    def test_save_logs_one_event_per_changed_field(self):
        response = self.client.post(self.url, self.form_data(modifiers_1="25", units_2="2", action="save"), follow=True)
        self.assertRedirects(response, self.url)
        self.assertContains(response, "Changes saved.")
        claim = self.refresh()
        self.assertEqual((claim.modifiers_1, claim.units_2), ("25", 2))
        events = {e.field: e for e in ClaimEvent.objects.filter(claim=claim, action=EventAction.EDIT)}
        self.assertEqual(set(events), {"modifiers_1", "units_2"})
        self.assertEqual((events["modifiers_1"].old_value, events["modifiers_1"].new_value), ("", "25"))
        self.assertEqual((events["units_2"].old_value, events["units_2"].new_value), ("1", "2"))
        self.assertEqual(events["units_2"].user, self.maria)
        self.assertContains(response, "changed Modifiers (line 1) from")

    def test_save_without_changes_logs_nothing(self):
        response = self.client.post(self.url, self.form_data(action="save"), follow=True)
        self.assertContains(response, "Nothing to save.")
        self.assertEqual(ClaimEvent.objects.filter(claim=self.claim).count(), 0)

    def test_invalid_form_shows_errors_near_the_field_and_saves_nothing(self):
        response = self.client.post(self.url, self.form_data(date_of_service="", modifiers_1="25", action="save"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        self.assertContains(response, "Some fields need a fix before this can be saved.")
        self.assertEqual(self.refresh().modifiers_1, "")
        self.assertEqual(ClaimEvent.objects.count(), 0)

    def test_answer_key_fields_cannot_be_posted(self):
        self.client.post(self.url, self.form_data(expected_action="submit", scored="on", work_status="submitted", action="save"))
        claim = Claim.objects.get(pk=self.claim.pk)
        self.assertEqual(claim.expected_action, "fix")
        self.assertFalse(claim.scored)
        self.assertEqual(claim.work_status, WorkStatus.NEW)

    @mock.patch("core.ai.httpx.post")
    def test_recheck_saves_the_form_then_reviews_again(self, post):
        self.review()
        post.return_value = reply(READY)
        response = self.client.post(self.review_url, self.form_data(modifiers_1="25"))
        claim = self.refresh()
        self.assertEqual(claim.modifiers_1, "25")
        self.assertEqual(claim.work_status, WorkStatus.READY)
        self.assertEqual(AIReview.objects.filter(claim=claim).count(), 2)
        self.assertContains(response, "No issues found")
        actions = list(ClaimEvent.objects.filter(claim=claim).order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, [EventAction.EDIT, EventAction.CHECK])
        self.assertIn('"modifiers_1": "25"', post.call_args.kwargs["json"]["messages"][1]["content"])

    @mock.patch("core.ai.httpx.post")
    def test_recheck_with_an_invalid_form_does_not_call_the_ai(self, post):
        response = self.client.post(self.review_url, self.form_data(date_of_service="not a date"))
        post.assert_not_called()
        self.assertContains(response, "Some fields need a fix before RUNG can check the claim.")
        self.assertContains(response, "Enter a valid date.")

    def test_changed_field_is_no_longer_flagged_and_review_is_marked_stale(self):
        self.review()
        self.client.post(self.url, self.form_data(modifiers_1="25", action="save"))
        response = self.client.get(self.url)
        self.assertTrue(response.context["stale"])
        self.assertContains(response, "The claim changed after this check.")
        self.assertContains(response, "Changed since check")
        self.assertEqual(response.context["groups"][2]["fields"][2]["hint"], "")


class SubmitAndCloseTests(WorkspaceTestCase):
    def test_submit_with_an_open_high_confidence_issue_asks_first(self):
        self.review()
        response = self.client.post(self.url, self.form_data(action="submit"))
        self.assertRedirects(response, f"{self.url}?confirm=submit", fetch_redirect_response=False)
        self.assertEqual(self.refresh().work_status, WorkStatus.NEW)
        page = self.client.get(response.url)
        self.assertContains(page, "Submit with open issues?")
        self.assertContains(page, SHOWN["minimal"])
        self.assertContains(page, 'value="submit_confirmed"')

    def test_confirming_submits_the_claim_and_the_payer_denies_it(self):
        self.review()
        response = self.client.post(self.url, self.form_data(action="submit_confirmed"), follow=True)
        self.assertRedirects(response, reverse("queue"))
        # The missing modifier was never added, so the simulated payer denies the claim.
        self.assertContains(response, "CLM-1012 was denied by the payer (CO-4). It is back in your queue to fix.")
        self.assertEqual(self.refresh().work_status, WorkStatus.DENIED)
        self.assertEqual(ClaimEvent.objects.filter(claim=self.claim, action=EventAction.SUBMIT).count(), 1)

    def test_fixing_the_flagged_field_submits_without_asking(self):
        self.review()
        response = self.client.post(self.url, self.form_data(modifiers_1="25", action="submit"))
        self.assertRedirects(response, reverse("queue"))
        claim = self.refresh()
        self.assertEqual((claim.work_status, claim.modifiers_1), (WorkStatus.PAID, "25"))
        actions = list(ClaimEvent.objects.filter(claim=claim).order_by("id").values_list("action", flat=True))
        self.assertEqual(actions, [EventAction.EDIT, EventAction.SUBMIT, EventAction.PAYER])

    def test_low_confidence_issue_does_not_block_submit(self):
        self.review({**NEEDS_FIX, "issues": [{**ISSUE, "confidence": "low"}]})
        self.assertRedirects(self.client.post(self.url, self.form_data(action="submit")), reverse("queue"))

    def test_ready_claim_submits_directly(self):
        self.claim = Claim.objects.get(claim_id="CLM-1001")
        self.url = reverse("claim", args=[self.claim.pk])
        self.review(READY)
        response = self.client.post(self.url, self.form_data(action="submit"), follow=True)
        self.assertRedirects(response, reverse("queue"))
        self.assertContains(response, "CLM-1001 submitted. The payer paid it.")
        self.assertEqual(self.refresh().work_status, WorkStatus.PAID)

    def test_close_needs_a_reason_and_logs_it(self):
        response = self.client.post(self.url, {"action": "close", "close_reason": ""}, follow=True)
        self.assertContains(response, "Choose a reason before closing the claim.")
        self.assertEqual(self.refresh().work_status, WorkStatus.NEW)
        response = self.client.post(self.url, {"action": "close", "close_reason": "duplicate"}, follow=True)
        self.assertRedirects(response, reverse("queue"))
        self.assertContains(response, "CLM-1012 closed.")
        self.assertEqual(self.refresh().work_status, WorkStatus.CLOSED)
        event = ClaimEvent.objects.get(claim=self.claim, action=EventAction.CLOSE)
        self.assertEqual(event.new_value, "Duplicate")

    def test_done_claim_is_read_only(self):
        Claim.objects.filter(pk=self.claim.pk).update(work_status=WorkStatus.PAID)
        self.assertContains(self.client.get(self.url), "The payer paid this claim. It can no longer be changed.")
        Claim.objects.filter(pk=self.claim.pk).update(work_status=WorkStatus.SUBMITTED)
        response = self.client.get(self.url)
        self.assertFalse(response.context["editable"])
        self.assertFalse(response.context["auto_review"])
        self.assertContains(response, "This claim was submitted. It can no longer be changed.")
        self.assertNotContains(response, "Submit claim")
        self.assertTrue(all(field.field.disabled for field in response.context["form"]))
        self.assertEqual(self.client.post(self.url, self.form_data(modifiers_1="25", action="save")).status_code, 403)
        self.assertEqual(self.refresh().modifiers_1, "")


class WorkspaceAccessTests(WorkspaceTestCase):
    def urls(self):
        return [("get", self.url), ("get", self.review_url)]

    def test_specialist_gets_403(self):
        self.client.force_login(self.dan)
        for method, url in self.urls():
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)

    def test_another_worker_gets_403(self):
        from core.models import Role

        self.client.force_login(make_user("other", Role.WORKER))
        for method, url in self.urls():
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, url)

    def test_anonymous_goes_to_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next={self.url}")


class AnswerKeyTests(WorkspaceTestCase):
    def test_answer_key_is_never_loaded_into_the_page_context(self):
        claim = self.client.get(self.url).context["claim"]
        self.assertEqual(claim.get_deferred_fields(), set(ANSWER_KEY_FIELDS))
        self.assertFalse(set(self.client.get(self.url).context["form"].fields) & set(ANSWER_KEY_FIELDS))

    @mock.patch("core.ai.httpx.post")
    def test_answer_key_never_appears_in_the_html_of_any_claim(self, post):
        post.return_value = reply(NEEDS_FIX)
        for claim in Claim.objects.all():
            pages = [
                self.client.get(reverse("claim", args=[claim.pk])),
                self.client.get(reverse("claim_review", args=[claim.pk])),
                self.client.get(reverse("claim", args=[claim.pk])),
            ]
            for response in pages:
                html = response.content.decode()
                self.assertNotIn("expected_", html, claim.claim_id)
                if claim.expected_issue:
                    self.assertNotIn(claim.expected_issue, html, claim.claim_id)


class ReviewFactsTests(WorkspaceTestCase):
    """The AI can only flag these four problems if the blocks give it the facts. These check the facts are sent."""

    def blocks(self, claim_id):
        return ai.build_blocks(Claim.objects.get(claim_id=claim_id))

    def test_clm_1024_member_id_rule_and_card_value_are_sent(self):
        blocks = self.blocks("CLM-1024")
        self.assertEqual(json.loads(blocks["claim"])["member_id"], "3WK4EO1RT57")
        self.assertIn("never use the letters S, L, O, I, B, or Z", blocks["payer_rules"])
        self.assertIn("3WK4E01RT57", blocks["clinical_note"])

    def test_clm_1028_deadline_facts_are_sent(self):
        blocks = self.blocks("CLM-1028")
        self.assertEqual(blocks["today"], "2026-11-16")
        self.assertEqual(json.loads(blocks["claim"])["date_of_service"], "2025-09-15")
        self.assertIn("Filing limit: 365 days.", blocks["payer_rules"])

    def test_clm_1029_earlier_duplicate_is_sent(self):
        earlier = json.loads(self.blocks("CLM-1029")["patient_claims"])
        claim = json.loads(self.blocks("CLM-1029")["claim"])
        self.assertEqual(earlier[0]["claim_id"], "CLM-1005")
        self.assertEqual(earlier[0]["date_of_service"], claim["date_of_service"])
        self.assertIn(claim["cpt_1"], earlier[0]["cpt_codes"])

    def test_clm_1022_inactive_coverage_is_sent(self):
        blocks = self.blocks("CLM-1022")
        self.assertEqual(json.loads(blocks["claim"])["eligibility_note"], "Inactive since 2026-08-31")
        self.assertIn("CRX20093357", blocks["clinical_note"])

    def test_a_flag_from_the_ai_shows_on_the_right_field(self):
        self.claim = Claim.objects.get(claim_id="CLM-1024")
        flag = {**ISSUE, "category": "eligibility", "field": "member_id", "full": "Member ID has the letter O. Use 3WK4E01RT57 from the card."}
        self.review({**NEEDS_FIX, "issues": [flag]})
        response = self.client.get(reverse("claim", args=[self.claim.pk]))
        hints = {item["field"].name: item["hint"] for group in response.context["groups"] for item in group["fields"]}
        self.assertEqual(hints["member_id"], flag["full"])
        self.assertContains(response, "Eligibility")


class PlainFieldNameTests(WorkspaceTestCase):
    def test_field_names_become_form_labels(self):
        text = plain_fields("icd10_primary and modifiers_1 need a fix; cpt_1 is fine. Not a field: icd10_primaryx")
        self.assertEqual(text, "Primary ICD-10 and Modifiers (line 1) need a fix; CPT (line 1) is fine. Not a field: icd10_primaryx")

    def test_every_claim_field_name_is_covered(self):
        text = plain_fields("denial_code CO-16; ndc_code missing; date_of_service late; prior_auth_number and place_of_service ok")
        self.assertEqual(text, "Denial code CO-16; NDC code missing; Date of service late; Prior auth number and Place of service ok")
        self.assertEqual(plain_fields("expected_action"), "expected_action")

    def test_the_review_panel_never_shows_a_raw_field_name(self):
        issue = {**ISSUE, "category": "code_matching", "field": "icd10_primary", "full": "icd10_primary should be E78.5.",
                 "guided": "icd10_primary: what is the lab monitoring?", "minimal": "Code matching: icd10_primary", "answer": "Set icd10_primary to E78.5."}
        self.review({**NEEDS_FIX, "summary": "icd10_primary needs a change.", "issues": [issue]})
        page = self.client.get(self.url)
        self.assertContains(page, "Primary ICD-10 should be E78.5.")
        self.assertContains(page, "Primary ICD-10 needs a change.")
        # The raw name still appears in the HTML as the input's own name, but never in the review text.
        self.assertNotIn("icd10_primary ", page.content.decode().split('id="review-panel"')[1].split("</aside>")[0].replace('id_icd10_primary', ''))
