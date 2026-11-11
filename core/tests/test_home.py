from django.urls import reverse

from core.models import Claim
from core.tests.base import SeededTestCase
from core.views.auth import CONTACT, FAQS


class HomePageTests(SeededTestCase):
    def setUp(self):
        self.response = self.client.get(reverse("home"))

    def test_anyone_can_open_the_home_page(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertContains(self.response, "Demo data only. Do not enter real patient information.")

    def test_hero_headline_and_sign_in_buttons(self):
        self.assertContains(self.response, "Expert billing help,")
        self.assertContains(self.response, "built into the work.")
        self.assertContains(self.response, f'href="{reverse("login")}"', count=4)

    def test_mission_statement(self):
        self.assertContains(self.response, "Our mission")
        self.assertContains(self.response, "expert work on day one")
        self.assertContains(self.response, "need less help every week after")

    def test_sections_for_both_audiences(self):
        for text in ("For billing workers", "For clinic owners", "How it works", "Help that fades", "A general chatbot"):
            self.assertContains(self.response, text)
        for anchor in ("how", "who", "mission", "faq", "contact"):
            self.assertContains(self.response, f'id="{anchor}"')
            self.assertContains(self.response, f'href="#{anchor}"')

    def test_questions_expand_and_collapse(self):
        for item in FAQS:
            self.assertContains(self.response, item["question"])
        self.assertContains(self.response, "x-collapse", count=len(FAQS))
        self.assertContains(self.response, "aria-expanded", count=len(FAQS))

    def test_contact_details_are_placeholders(self):
        self.assertContains(self.response, CONTACT["email"])
        self.assertContains(self.response, CONTACT["phone"])
        self.assertContains(self.response, CONTACT["address"])
        self.assertContains(self.response, "Placeholder details.")
        self.assertTrue(CONTACT["email"].endswith("@example.com"))

    def test_home_page_shows_no_claim_data(self):
        html = self.response.content.decode()
        for claim in Claim.objects.all():
            self.assertNotIn(claim.patient_last, html)
            self.assertNotIn(claim.member_id, html)

    def test_signed_in_users_skip_the_home_page(self):
        self.client.force_login(self.maria)
        self.assertRedirects(self.client.get(reverse("home")), reverse("queue"))
        self.client.force_login(self.dan)
        self.assertRedirects(self.client.get(reverse("home")), reverse("help_list"))
