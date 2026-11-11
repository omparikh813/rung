import json
from unittest import mock

import httpx
from django.conf import settings
from django.test import override_settings

from core import ai
from core.claims import ANSWER_KEY_FIELDS
from core.models import AIReview, CaseEntry, Category, Claim
from core.tests.base import SeededTestCase

API_KEY = "sk-test-secret-key"

READY = {"summary": "This claim is ready.", "ready_to_submit": True, "issues": [], "escalate": False, "escalate_reason": None}

ISSUE = {
    "category": "modifiers",
    "field": "modifiers_1",
    "full": "modifiers_1 needs modifier 25 because the visit was separate. Source: All payers rule.",
    "guided": "modifiers_1: what tells the payer the visit was separate from the injection?",
    "minimal": "Modifiers: modifiers_1",
    "answer": "Add modifier 25 to line 1. Source: All payers rule.",
    "suggested_value": "25",
    "confidence": "high",
    "escalate": False,
}
NEEDS_FIX = {"summary": "One modifier is missing.", "ready_to_submit": False, "issues": [ISSUE], "escalate": False, "escalate_reason": None}


def reply(content, prompt_tokens=3000, completion_tokens=600):
    """A fake OpenRouter response. content may be a dict (sent as JSON text) or raw text."""
    text = content if isinstance(content, str) else json.dumps(content)
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }
    return response


def api_error(status=500):
    request = httpx.Request("POST", ai.URL)
    response = mock.Mock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server error", request=request, response=httpx.Response(status, request=request)
    )
    return response


@mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": API_KEY})
class AIClientTests(SeededTestCase):
    def claim(self, claim_id):
        return Claim.objects.get(claim_id=claim_id)

    @mock.patch("core.ai.httpx.post")
    def test_request_uses_master_prompt_task_prompt_model_and_key(self, post):
        post.return_value = reply(READY)
        ai.review_claim(self.claim("CLM-1001"))
        (url,), kwargs = post.call_args
        self.assertEqual(url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"], {"Authorization": f"Bearer {API_KEY}"})
        payload = kwargs["json"]
        self.assertEqual(payload["model"], settings.RUNG_MODEL)
        self.assertEqual(payload["temperature"], 0)
        system, user = payload["messages"]
        self.assertEqual(system, {"role": "system", "content": (settings.BASE_DIR / "prompts" / "master.md").read_text()})
        task = (settings.BASE_DIR / "prompts" / "review_claim.md").read_text()
        self.assertTrue(user["content"].endswith(f"<task>\n{task}\n</task>"))
        order = [user["content"].index(f"<{tag}>") for tag in ("today", "claim", "clinical_note", "payer_rules", "patient_claims", "similar_cases", "task")]
        self.assertEqual(order, sorted(order))

    @override_settings(RUNG_MODEL="some/other-model")
    @mock.patch("core.ai.httpx.post")
    def test_model_comes_from_settings(self, post):
        post.return_value = reply(READY)
        review = ai.review_claim(self.claim("CLM-1001"))
        self.assertEqual(post.call_args.kwargs["json"]["model"], "some/other-model")
        self.assertEqual(review.model, "some/other-model")

    @mock.patch("core.ai.httpx.post")
    def test_answer_key_is_never_sent(self, post):
        post.return_value = reply(READY)
        for claim in Claim.objects.all():
            AIReview.objects.all().delete()
            ai.review_claim(claim)
            sent = json.dumps(post.call_args.kwargs["json"])
            for name in ANSWER_KEY_FIELDS:
                self.assertNotIn(name, sent, claim.claim_id)
            if claim.expected_issue:
                self.assertNotIn(json.dumps(claim.expected_issue)[1:-1], sent, claim.claim_id)
        self.assertEqual(post.call_count, 30)

    def test_claim_block_has_visible_fields_only(self):
        block = ai.claim_block(self.claim("CLM-1012"))
        self.assertEqual(block["cpt_2"], "20610")
        self.assertEqual(block["charge_1"], "150.00")
        self.assertEqual(block["date_of_service"], "2026-10-23")
        self.assertFalse(set(block) & set(ANSWER_KEY_FIELDS))
        self.assertNotIn("assigned_to", block)

    def test_blocks_for_a_medicare_claim(self):
        blocks = ai.build_blocks(self.claim("CLM-1024"))
        self.assertEqual(blocks["today"], "2026-11-16")
        self.assertIn("Scanned Medicare card reads 3WK4E01RT57", blocks["clinical_note"])
        rules = blocks["payer_rules"]
        self.assertIn("Medicare IDs are 11 characters", rules)
        self.assertIn("(source: Medicare (real rule))", rules)
        self.assertIn("Filing limit: 365 days.", rules)
        self.assertIn("Injury codes (S and T codes) need a 7th character", rules)
        self.assertNotIn("Summit Health PPO", rules)
        self.assertEqual(len(rules.splitlines()), 11)
        self.assertEqual(blocks["patient_claims"], "none")
        self.assertEqual(blocks["similar_cases"], "none")

    def test_only_the_later_claim_sees_the_earlier_one(self):
        self.assertEqual(ai.patient_claims_block(self.claim("CLM-1005")), "none")
        earlier = json.loads(ai.patient_claims_block(self.claim("CLM-1029")))
        self.assertEqual(
            earlier, [{"claim_id": "CLM-1005", "date_of_service": "2026-10-28", "cpt_codes": ["93000"], "status": "New"}]
        )

    def test_similar_cases_block_has_no_more_than_three_entries(self):
        for number in range(4):
            CaseEntry.objects.create(
                title=f"Routine physical {number}", category=Category.CODE_MATCHING, payer_name="Medicare Part B",
                codes="99397, Z00.00", problem="p", fix="f", tip="t", created_by=self.dan,
            )
        CaseEntry.objects.create(title="Unrelated", category=Category.MODIFIERS, codes="12345", problem="p", fix="f")
        # CLM-1017 is Medicare with diagnosis Z00.00: same payer and diagnosis.
        rows = json.loads(ai.similar_cases_block(self.claim("CLM-1017")))
        self.assertEqual(len(rows), 3)
        self.assertEqual(set(rows[0]), {"title", "problem", "fix", "tip"})
        self.assertNotIn("Unrelated", [row["title"] for row in rows])

    @mock.patch("core.ai.httpx.post")
    def test_review_is_stored_with_token_counts(self, post):
        post.return_value = reply(NEEDS_FIX, prompt_tokens=2890, completion_tokens=412)
        claim = self.claim("CLM-1012")
        review = ai.review_claim(claim)
        self.assertEqual(AIReview.objects.filter(claim=claim).count(), 1)
        self.assertEqual(review.input_tokens, 2890)
        self.assertEqual(review.output_tokens, 412)
        self.assertEqual(review.claim_version_hash, ai.claim_version_hash(claim))
        self.assertEqual(review.result_json["issues"][0]["suggested_value"], "25")
        self.assertFalse(review.result_json["ready_to_submit"])

    @mock.patch("core.ai.httpx.post")
    def test_latest_review_is_reused_until_the_claim_changes(self, post):
        post.return_value = reply(NEEDS_FIX)
        claim = self.claim("CLM-1012")
        first = ai.review_claim(claim)
        self.assertEqual(ai.review_claim(claim).pk, first.pk)
        self.assertEqual(post.call_count, 1)
        claim.modifiers_1 = "25"
        claim.save()
        post.return_value = reply(READY)
        second = ai.review_claim(claim)
        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(post.call_count, 2)
        self.assertTrue(second.result_json["ready_to_submit"])

    @mock.patch("core.ai.httpx.post")
    def test_bad_json_triggers_one_retry(self, post):
        post.side_effect = [reply("Sure! Here is my review of the claim."), reply(READY)]
        review = ai.review_claim(self.claim("CLM-1001"))
        self.assertEqual(post.call_count, 2)
        retry_messages = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(retry_messages[-1], {"role": "user", "content": "Return valid JSON only."})
        self.assertTrue(review.result_json["ready_to_submit"])

    @mock.patch("core.ai.httpx.post")
    def test_two_bad_replies_raise_ai_error_and_store_nothing(self, post):
        post.return_value = reply("still not json")
        with self.assertRaises(ai.AIError), self.assertLogs("core.ai", "WARNING"):
            ai.review_claim(self.claim("CLM-1001"))
        self.assertEqual(post.call_count, 2)
        self.assertEqual(AIReview.objects.count(), 0)

    @mock.patch("core.ai.httpx.post")
    def test_code_fences_are_stripped(self, post):
        post.return_value = reply("```json\n" + json.dumps(READY) + "\n```")
        review = ai.review_claim(self.claim("CLM-1001"))
        self.assertEqual(post.call_count, 1)
        self.assertEqual(review.result_json["summary"], "This claim is ready.")

    @mock.patch("core.ai.httpx.post")
    def test_api_error_raises_ai_error_without_leaking_the_key(self, post):
        for failure in (api_error(500), httpx.ConnectTimeout("timed out")):
            post.reset_mock(side_effect=True, return_value=True)
            if isinstance(failure, Exception):
                post.side_effect = failure
            else:
                post.return_value = failure
            with self.assertRaises(ai.AIError) as raised, self.assertLogs("core.ai", "WARNING") as logs:
                ai.review_claim(self.claim("CLM-1001"))
            self.assertNotIn(API_KEY, str(raised.exception))
            self.assertNotIn(API_KEY, " ".join(logs.output))
        self.assertEqual(AIReview.objects.count(), 0)

    @mock.patch("core.ai.httpx.post")
    def test_missing_api_key_raises_ai_error(self, post):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ai.AIError), self.assertLogs("core.ai", "WARNING"):
                ai.review_claim(self.claim("CLM-1001"))
        post.assert_not_called()

    @mock.patch("core.ai.httpx.post")
    def test_wrong_shape_raises_ai_error(self, post):
        post.return_value = reply({"summary": "no issues list"})
        with self.assertRaises(ai.AIError), self.assertLogs("core.ai", "WARNING"):
            ai.review_claim(self.claim("CLM-1001"))

    def test_clean_review_enforces_the_task_rules(self):
        cleaned = ai.clean_review(
            {
                "summary": "x",
                "ready_to_submit": True,
                "issues": [{"category": "made_up", "field": "cpt_1", "full": "Full text", "escalate": True}],
                "escalate": False,
            }
        )
        issue = cleaned["issues"][0]
        # ready_to_submit is true only when issues is empty.
        self.assertFalse(cleaned["ready_to_submit"])
        # Top level escalate is true if any issue has escalate true.
        self.assertTrue(cleaned["escalate"])
        self.assertEqual(issue["category"], "")
        self.assertEqual(issue["confidence"], "low")
        # Guided and minimal never fall back to the text that reveals the fix.
        self.assertEqual(issue["minimal"], "Claim: cpt_1")
        self.assertEqual(issue["guided"], "Claim: cpt_1")
        self.assertIsNone(issue["suggested_value"])


class PromptFileTests(SeededTestCase):
    def test_prompt_files_match_the_prd(self):
        master = (settings.BASE_DIR / "prompts" / "master.md").read_text()
        task = (settings.BASE_DIR / "prompts" / "review_claim.md").read_text()
        self.assertTrue(master.startswith("# RUNG master prompt (v1)"))
        self.assertIn("8. All data is fictional demo data. Never ask for or repeat real patient information.", master)
        self.assertIn("Return only the JSON object described in <task>. No text before or after it.", master)
        self.assertTrue(task.startswith("Review this claim before it is submitted"))
        self.assertIn('- If a similar case matches, use its fix and mention it in "answer".', task)
