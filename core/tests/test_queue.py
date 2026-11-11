from django.test import SimpleTestCase
from django.urls import reverse

from core.claims import days_left_to_file, days_left_tone, filing_limits
from core.models import AIReview, Claim, WorkStatus
from core.tests.base import SeededTestCase


class DaysLeftTests(SimpleTestCase):
    def test_tone_thresholds(self):
        self.assertEqual(days_left_tone(-1), "expired")
        self.assertEqual(days_left_tone(0), "red")
        self.assertEqual(days_left_tone(14), "red")
        self.assertEqual(days_left_tone(15), "amber")
        self.assertEqual(days_left_tone(29), "amber")
        self.assertEqual(days_left_tone(30), "")
        self.assertEqual(days_left_tone(None), "")


class QueueTests(SeededTestCase):
    def get(self, **params):
        return self.client.get(reverse("queue"), params)

    def test_worker_lands_on_queue(self):
        self.assertRedirects(self.client.get(reverse("home")), reverse("queue"))

    def test_specialist_cannot_open_queue(self):
        self.client.force_login(self.dan)
        self.assertEqual(self.get().status_code, 403)

    def test_all_30_claims_appear_with_days_left_from_demo_today(self):
        claims = self.get().context["claims"]
        self.assertEqual(len(claims), 30)
        limits = filing_limits()
        by_id = {claim.claim_id: claim for claim in claims}
        # Summit: 180 day limit, service on 2026-10-20, 27 days before the demo date.
        self.assertEqual(by_id["CLM-1001"].days_left, 153)
        # Bayview: 90 day limit, service on 2026-11-02.
        self.assertEqual(by_id["CLM-1011"].days_left, 76)
        # Medicare: 365 day limit, service on 2025-09-15.
        self.assertEqual(by_id["CLM-1028"].days_left, -62)
        self.assertEqual(by_id["CLM-1028"].days_tone, "expired")
        for claim in claims:
            self.assertEqual(claim.days_left, days_left_to_file(claim, limits))

    def test_clm_1028_shows_expired(self):
        response = self.get(q="CLM-1028")
        self.assertContains(response, "Expired")
        self.assertNotContains(self.get(q="CLM-1001"), "Expired")

    def test_default_sort_is_days_left_lowest_first(self):
        claims = self.get().context["claims"]
        days = [claim.days_left for claim in claims]
        self.assertEqual(days, sorted(days))
        self.assertEqual(claims[0].claim_id, "CLM-1028")

    def test_tabs_filter_by_status_and_show_counts(self):
        Claim.objects.filter(claim_id="CLM-1001").update(work_status=WorkStatus.SUBMITTED)
        Claim.objects.filter(claim_id="CLM-1002").update(work_status=WorkStatus.CLOSED)
        Claim.objects.filter(claim_id="CLM-1009").update(work_status=WorkStatus.WAITING)
        Claim.objects.filter(claim_id="CLM-1012").update(work_status=WorkStatus.NEEDS_FIX)
        response = self.get()
        counts = {tab["key"]: tab["count"] for tab in response.context["tabs"]}
        self.assertEqual(counts, {"open": 27, "needs_fix": 1, "denied": 6, "waiting": 1, "done": 2})
        self.assertEqual(response.context["open_count"], 27)
        self.assertEqual([c.claim_id for c in self.get(tab="needs_fix").context["claims"]], ["CLM-1012"])
        self.assertEqual([c.claim_id for c in self.get(tab="waiting").context["claims"]], ["CLM-1009"])
        self.assertEqual({c.claim_id for c in self.get(tab="done").context["claims"]}, {"CLM-1001", "CLM-1002"})
        self.assertEqual(len(self.get(tab="denied").context["claims"]), 6)

    def test_search_by_claim_id_or_last_name(self):
        self.assertEqual([c.claim_id for c in self.get(q="1012").context["claims"]], ["CLM-1012"])
        self.assertEqual({c.claim_id for c in self.get(q="sokolov").context["claims"]}, {"CLM-1005", "CLM-1029"})
        self.assertContains(self.get(q="zzz"), "No claims match your search")

    def test_htmx_request_gets_only_the_table(self):
        response = self.client.get(reverse("queue"), {"tab": "waiting"}, headers={"HX-Request": "true"})
        self.assertTemplateUsed(response, "core/partials/queue_table.html")
        self.assertTemplateNotUsed(response, "core/base.html")
        self.assertContains(response, "Claims you have sent to a specialist will appear here.")

    def test_only_own_claims_are_listed(self):
        Claim.objects.filter(claim_id="CLM-1003").update(assigned_to=None)
        self.assertEqual(len(self.get().context["claims"]), 29)

    def test_open_issue_count_comes_from_the_latest_review(self):
        claim = Claim.objects.get(claim_id="CLM-1012")
        AIReview.objects.create(claim=claim, result_json={"issues": [{}, {}]}, model="m", claim_version_hash="x")
        row = self.get(q="CLM-1012").context["claims"][0]
        self.assertEqual(row.open_issues, 2)
        self.assertIsNone(self.get(q="CLM-1001").context["claims"][0].open_issues)

    def test_answer_key_is_not_in_the_page(self):
        response = self.get()
        for claim in Claim.objects.exclude(expected_issue=""):
            self.assertNotContains(response, claim.expected_issue)
