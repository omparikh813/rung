from django.urls import reverse

from core.claims import similar_cases
from core.models import CaseEntry, Category, Claim, Role
from core.tests.base import SeededTestCase, make_user


class LibraryTestCase(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.physical = CaseEntry.objects.create(
            title="Routine physical billed to Medicare", category=Category.CODE_MATCHING, payer_name="Medicare Part B",
            codes="99397, Z00.00", problem="Medicare does not cover routine physicals.",
            fix="Add modifier GY so the patient can be billed.", tip="Check the Annual Wellness Visit rules first.",
            created_by=self.dan,
        )  # fmt: skip
        self.auth = CaseEntry.objects.create(
            title="Missing auth number on knee surgery", category=Category.PRIOR_AUTH, payer_name="Summit Health PPO",
            codes="29881", denial_code="CO-197", problem="The approval existed but was left off.",
            fix="Add the number from the scheduling note and resend.", created_by=self.dan,
        )  # fmt: skip

    def titles(self, **params):
        return [entry.title for entry in self.client.get(reverse("library"), params).context["entries"]]


class LibraryListTests(LibraryTestCase):
    def test_both_roles_can_read_the_library(self):
        for user in (self.maria, self.dan):
            self.client.force_login(user)
            response = self.client.get(reverse("library"))
            self.assertEqual(response.status_code, 200)
            for text in (self.physical.title, "Code matching", "Medicare Part B", "99397, Z00.00", self.physical.problem, self.physical.fix, self.physical.tip, "Dan"):
                self.assertContains(response, text)

    def test_search_covers_title_problem_fix_and_codes(self):
        self.assertEqual(self.titles(q="99397"), [self.physical.title])
        self.assertEqual(self.titles(q="knee"), [self.auth.title])
        self.assertEqual(self.titles(q="left off"), [self.auth.title])
        self.assertEqual(self.titles(q="modifier GY"), [self.physical.title])
        self.assertEqual(self.titles(q="nothing like this"), [])

    def test_category_and_payer_filters(self):
        self.assertEqual(self.titles(category="prior_auth"), [self.auth.title])
        self.assertEqual(self.titles(payer="Medicare Part B"), [self.physical.title])
        self.assertEqual(self.titles(category="prior_auth", payer="Medicare Part B"), [])
        response = self.client.get(reverse("library"))
        self.assertEqual(list(response.context["payers"]), ["Medicare Part B", "Summit Health PPO"])

    def test_htmx_search_returns_only_the_cards(self):
        response = self.client.get(reverse("library"), {"q": "knee"}, headers={"HX-Request": "true"})
        self.assertTemplateUsed(response, "core/partials/library_cards.html")
        self.assertTemplateNotUsed(response, "core/base.html")
        self.assertContains(response, self.auth.title)
        self.assertNotContains(response, self.physical.title)

    def test_empty_states(self):
        self.assertContains(self.client.get(reverse("library"), {"q": "zzz"}), "No entries match")
        CaseEntry.objects.all().delete()
        response = self.client.get(reverse("library"))
        self.assertContains(response, "Entries appear here when specialists resolve help requests and save the fix.")


class LibraryDetailTests(LibraryTestCase):
    def test_detail_shows_the_full_entry(self):
        response = self.client.get(reverse("library_detail", args=[self.physical.pk]))
        for text in (self.physical.title, self.physical.problem, self.physical.fix, self.physical.tip, "Saved by Dan"):
            self.assertContains(response, text)

    def test_only_the_author_sees_edit_and_delete(self):
        url = reverse("library_detail", args=[self.physical.pk])
        self.assertNotContains(self.client.get(url), reverse("library_edit", args=[self.physical.pk]))
        self.client.force_login(make_user("erin", Role.SPECIALIST))
        self.assertFalse(self.client.get(url).context["can_change"])
        self.client.force_login(self.dan)
        response = self.client.get(url)
        self.assertContains(response, reverse("library_edit", args=[self.physical.pk]))
        self.assertContains(response, reverse("library_delete", args=[self.physical.pk]))

    def test_author_can_edit(self):
        self.client.force_login(self.dan)
        url = reverse("library_edit", args=[self.physical.pk])
        data = {**self.client.get(url).context["form"].initial, "title": "Routine physical: use GY"}
        response = self.client.post(url, data, follow=True)
        self.assertRedirects(response, reverse("library_detail", args=[self.physical.pk]))
        self.assertContains(response, "Case Library entry saved.")
        self.physical.refresh_from_db()
        self.assertEqual(self.physical.title, "Routine physical: use GY")
        self.assertContains(self.client.post(url, {**data, "fix": ""}), "This field is required.")

    def test_author_can_delete_with_post_only(self):
        self.client.force_login(self.dan)
        url = reverse("library_delete", args=[self.physical.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), reverse("library"))
        self.assertFalse(CaseEntry.objects.filter(pk=self.physical.pk).exists())

    def test_workers_and_other_specialists_cannot_edit_or_delete(self):
        for user in (self.maria, make_user("erin", Role.SPECIALIST)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("library_edit", args=[self.physical.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("library_delete", args=[self.physical.pk])).status_code, 403)
        self.assertTrue(CaseEntry.objects.filter(pk=self.physical.pk).exists())


class SimilarCaseTests(LibraryTestCase):
    def claim(self, claim_id):
        return Claim.objects.get(claim_id=claim_id)

    def test_match_on_same_cpt_code(self):
        self.assertEqual(similar_cases(self.claim("CLM-1021")), [self.physical])
        self.assertEqual(similar_cases(self.claim("CLM-1010")), [self.auth])

    def test_match_on_same_payer_and_diagnosis(self):
        # CLM-1017 is a Medicare lab claim with diagnosis Z00.00, like the routine physical entry.
        self.assertEqual(similar_cases(self.claim("CLM-1017")), [self.physical])
        # Same diagnosis but a different payer is not a match.
        CaseEntry.objects.filter(pk=self.physical.pk).update(payer_name="Summit Health PPO")
        self.assertEqual(similar_cases(self.claim("CLM-1017")), [])

    def test_match_on_same_denial_code(self):
        CaseEntry.objects.filter(pk=self.auth.pk).update(codes="")
        self.assertEqual(similar_cases(self.claim("CLM-1010")), [self.auth])

    def test_no_match_and_at_most_three(self):
        self.assertEqual(similar_cases(self.claim("CLM-1001")), [])
        for number in range(4):
            CaseEntry.objects.create(title=f"Extra {number}", category=Category.CODE_MATCHING, codes="99397", problem="p", fix="f")
        self.assertEqual(len(similar_cases(self.claim("CLM-1021"))), 3)

    def test_saved_entry_appears_as_a_similar_case_on_a_related_claim(self):
        response = self.client.get(reverse("claim", args=[self.claim("CLM-1017").pk]))
        self.assertContains(response, "Similar cases")
        self.assertContains(response, self.physical.title)
        self.assertContains(response, reverse("library_detail", args=[self.physical.pk]))
        other = self.client.get(reverse("claim", args=[self.claim("CLM-1001").pk]))
        self.assertContains(other, "No similar cases yet.")
        self.assertNotContains(other, self.physical.title)
