import re

from django.urls import reverse

from core.models import Organization
from core.organizations import DIRECTORY
from core.tests.base import SeededTestCase

URL = reverse("start")


class StartUsingRungTests(SeededTestCase):
    def setUp(self):
        self.client.logout()

    def test_button_under_the_sign_in_box(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Start Using RUNG")
        html = response.content.decode()
        self.assertLess(html.index('type="submit"'), html.index(f'href="{URL}"'))

    def test_the_steps_are_all_there(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        for text in ("Your account", "Your organization", "Team size", "Review", "Organization type", "Company directory",
                     "Other / not listed", "How many employees need RUNG access?", "Medical billing company",
                     "RCM outsourcing company", "you become its Organization Admin"):  # fmt: skip
            self.assertContains(response, text)
        for seats in ("1–5", "6–20", "21–50", "51–100", "101–250", "251–500", "500+"):
            self.assertContains(response, seats)
        for company in DIRECTORY:
            self.assertIn(company.replace("&", "&amp;"), response.content.decode().replace("&quot;", '"'))

    def test_it_cannot_create_an_organization(self):
        response = self.client.get(URL)
        self.assertContains(response, "Creating new organizations opens once RUNG's database is set up")
        self.assertContains(response, 'disabled aria-disabled="true"')
        self.assertNotContains(response, "<form")
        self.assertEqual(self.client.post(URL, {"name": "New Co"}).status_code, 405)
        self.assertEqual(Organization.objects.count(), 2)

    def test_no_prices(self):
        html = self.client.get(URL).content.decode()
        self.assertIsNone(re.search(r"\$\s?\d", html))
        self.assertNotIn("per seat", html.lower())
