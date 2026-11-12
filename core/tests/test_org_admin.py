import re

from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import Role
from core.tests.base import PASSWORD, SeededTestCase

URL = reverse("organization")


class OrgAdminTestCase(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.om)
        User = get_user_model()
        self.cassandra = User.objects.get(username="cassandra")
        self.kevin = User.objects.get(username="kevin")
        self.nina = User.objects.get(username="nina")
        self.leo = User.objects.get(username="leo")

    def act(self, user, action, **data):
        return self.client.post(reverse("employee_update", args=[user.pk]), {"action": action, **data}, follow=True)

    def role(self, user):
        user.profile.refresh_from_db()
        return user.profile.role


class DashboardTests(OrgAdminTestCase):
    def test_only_admins_open_the_dashboard(self):
        self.assertEqual(self.client.get(URL).status_code, 200)
        for user in (self.maria, self.dan):
            self.client.force_login(user)
            self.assertEqual(self.client.get(URL).status_code, 403)

    def test_admin_lands_on_the_dashboard(self):
        self.assertRedirects(self.client.get(reverse("home")), URL)
        links = [item["label"] for item in self.client.get(URL).context["nav_items"]]
        self.assertEqual(links[0], "Organization")

    def test_overview_counts_and_seats(self):
        response = self.client.get(URL)
        tiles = {tile["label"]: tile["value"] for tile in response.context["tiles"]}
        self.assertEqual(tiles, {"Active employees": 5, "Seats left of 10": 5, "Workers": 3, "Specialists": 1, "Admins": 1})
        self.assertEqual(response.context["seat_percent"], 50)
        self.assertContains(response, "Ready for promotion")
        self.assertEqual(response.context["ready_count"], 1)

    def test_every_section_opens(self):
        for section, text in (
            ("employees", "Team members"),
            ("performance", "Worker performance"),
            ("settings", "Organization settings"),
            ("subscription", "Features in this contract"),
        ):
            self.assertContains(self.client.get(URL, {"section": section}), text)

    def test_employees_lists_only_this_organization(self):
        response = self.client.get(URL, {"section": "employees"})
        usernames = [person.username for person in response.context["people"]]
        self.assertEqual(sorted(usernames), ["cassandra", "flora", "james", "kevin", "om"])
        self.assertNotContains(response, "nina")
        self.assertContains(response, "Invitations need email, which this demo does not have yet.")

    def test_performance_puts_cassandra_first_as_ready(self):
        rows = self.client.get(URL, {"section": "performance"}).context["rows"]
        self.assertEqual(rows[0]["user"], self.cassandra)
        self.assertTrue(rows[0]["ready"])
        self.assertEqual(rows[0]["accuracy"], 90)
        self.assertEqual([row["user"].username for row in rows if row["ready"]], ["cassandra"])

    def test_subscription_shows_tier_and_no_prices(self):
        response = self.client.get(URL, {"section": "subscription"})
        self.assertEqual((response.context["tier"], response.context["plan"]), ("Small Business", "Team"))
        self.assertContains(response, "Active")
        self.assertContains(response, "2027-06-30")
        self.assertIsNone(re.search(r"\$\s?\d", response.content.decode()))
        self.assertNotContains(response, "Request more seats")


class EmployeeActionTests(OrgAdminTestCase):
    def test_promote_cassandra_to_specialist(self):
        response = self.act(self.cassandra, "role", role="specialist", section="performance")
        self.assertRedirects(response, f"{URL}?section=performance")
        self.assertContains(response, "Cassandra was promoted to Specialist.")
        self.assertEqual(self.role(self.cassandra), Role.SPECIALIST)
        # She now has the specialist's tools.
        self.client.force_login(self.cassandra)
        self.assertRedirects(self.client.get(reverse("home")), reverse("help_list"))

    def test_change_role(self):
        self.act(self.dan, "role", role="worker")
        self.assertEqual(self.role(self.dan), Role.WORKER)
        response = self.act(self.dan, "role", role="admin")
        self.assertContains(response, "James is now Organization Admin.")
        self.assertEqual(self.role(self.dan), Role.ADMIN)

    def test_deactivate_frees_a_seat_and_blocks_sign_in(self):
        self.act(self.kevin, "deactivate")
        self.kevin.refresh_from_db()
        self.assertFalse(self.kevin.is_active)
        self.assertEqual(self.ags.seats_left, 6)
        self.client.logout()
        response = self.client.post(reverse("login"), {"organization": self.ags.pk, "username": "kevin", "password": PASSWORD})
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "That organization, username, or password is not right.")

    def test_reactivate_respects_the_seat_limit(self):
        self.act(self.kevin, "deactivate")
        self.ags.seat_limit = 4
        self.ags.save()
        response = self.act(self.kevin, "reactivate")
        self.assertContains(response, "All 4 seats are in use, so Kevin cannot be reactivated.")
        self.kevin.refresh_from_db()
        self.assertFalse(self.kevin.is_active)
        self.ags.seat_limit = 10
        self.ags.save()
        self.assertContains(self.act(self.kevin, "reactivate"), "Kevin was reactivated.")

    def test_admin_cannot_change_themselves(self):
        self.assertEqual(self.act(self.om, "role", role="worker").status_code, 403)
        self.assertEqual(self.act(self.om, "deactivate").status_code, 403)
        self.assertEqual(self.role(self.om), Role.ADMIN)

    def test_admin_cannot_touch_another_organizations_people(self):
        self.assertEqual(self.act(self.leo, "deactivate").status_code, 404)
        self.leo.refresh_from_db()
        self.assertTrue(self.leo.is_active)

    def test_others_cannot_manage_employees(self):
        for user in (self.maria, self.dan):
            self.client.force_login(user)
            self.assertEqual(self.act(self.kevin, "deactivate").status_code, 403)

    def test_bad_input_is_rejected(self):
        self.assertEqual(self.act(self.kevin, "role", role="owner").status_code, 403)
        self.assertEqual(self.act(self.kevin, "delete").status_code, 403)
        self.assertEqual(self.client.get(reverse("employee_update", args=[self.kevin.pk])).status_code, 405)
