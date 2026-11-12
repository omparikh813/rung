from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.decorators import role_required
from core.models import Role
from core.models import CaseEntry, Category, Claim, HelpRequest
from core.tests.base import PASSWORD, RoleTestCase, SeededTestCase, make_user

class RoleRequiredTests(RoleTestCase):
    def setUp(self):
        self.view = role_required(Role.WORKER)(lambda request: HttpResponse("ok"))
        self.request = RequestFactory().get("/worker-only/")

    def test_matching_role_gets_in(self):
        self.request.user = self.maria
        self.assertEqual(self.view(self.request).status_code, 200)

    def test_other_role_gets_403(self):
        self.request.user = self.dan
        with self.assertRaises(PermissionDenied):
            self.view(self.request)

    def test_user_without_profile_gets_403(self):
        self.request.user = make_user("nobody", role="")
        with self.assertRaises(PermissionDenied):
            self.view(self.request)

    def test_anonymous_goes_to_login(self):
        self.request.user = AnonymousUser()
        response = self.view(self.request)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)


class LoginTests(RoleTestCase):
    def test_login_page_shows_brand_banner_and_tagline(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Expert billing help, built into the work.")
        self.assertContains(response, "Demo data only. Do not enter real patient information.")
        self.assertContains(response, "rung_mark.png")

    @override_settings(DEBUG=True)
    def test_debug_hint_lists_usernames_but_no_password(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Demo accounts")
        self.assertContains(response, "maria")
        self.assertContains(response, "dan")
        self.assertNotContains(response, PASSWORD)

    @override_settings(DEBUG=False)
    def test_no_hint_when_debug_is_off(self):
        self.assertNotContains(self.client.get(reverse("login")), "Demo accounts")

    def test_wrong_credentials_show_one_message_that_names_no_field(self):
        for data in ({"username": "maria", "password": "wrong"}, {"username": "nobody", "password": PASSWORD}):
            response = self.client.post(reverse("login"), data)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "That username or password is not right. Please try again.", count=1)

    def test_good_credentials_sign_in_and_logout_signs_out(self):
        response = self.client.post(reverse("login"), {"username": "maria", "password": PASSWORD})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.maria.pk)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_home_page_is_public(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")

    def test_user_without_a_role_gets_403(self):
        self.client.force_login(make_user("nobody", role=""))
        self.assertEqual(self.client.get(reverse("home")).status_code, 403)


class RouteAccessTests(SeededTestCase):
    """Each role reaches only its own pages. Every other route returns 403."""

    def setUp(self):
        super().setUp()
        claim = Claim.objects.get(claim_id="CLM-1021")
        help_request = HelpRequest.objects.create(claim=claim, worker=self.maria, question="Help?")
        entry = CaseEntry.objects.create(title="t", category=Category.MODIFIERS, problem="p", fix="f", created_by=self.dan)
        self.other_worker = make_user("other", Role.WORKER)
        # Route, then the status each role should get: worker (maria), specialist (dan).
        self.routes = [
            (reverse("queue"), 200, 403),
            (reverse("claim", args=[claim.pk]), 200, 302),
            (reverse("claim_review", args=[claim.pk]), 200, 200),
            (reverse("help_list"), 200, 200),
            (reverse("help_detail", args=[help_request.pk]), 403, 200),
            (reverse("library"), 200, 200),
            (reverse("library_detail", args=[entry.pk]), 200, 200),
            (reverse("library_edit", args=[entry.pk]), 403, 200),
            (reverse("passport"), 200, 302),
            (reverse("passport_user", args=["maria"]), 200, 200),
            (reverse("passport_user", args=["other"]), 403, 200),
            (reverse("upload"), 200, 403),
            (reverse("claim_new"), 200, 403),
            (reverse("training"), 200, 403),
            (reverse("upload_template"), 200, 403),
        ]
        # The review endpoint would call the AI, so give the claim a stored review first.
        from core import ai
        from core.models import AIReview
        from core.tests.test_ai_client import READY

        AIReview.objects.create(
            claim=claim, result_json=ai.clean_review(READY), model="m", claim_version_hash=ai.claim_version_hash(claim)
        )

    def test_worker_routes(self):
        for url, expected, _ in self.routes:
            self.assertEqual(self.client.get(url).status_code, expected, url)

    def test_specialist_routes(self):
        self.client.force_login(self.dan)
        for url, _, expected in self.routes:
            self.assertEqual(self.client.get(url).status_code, expected, url)

    def test_a_worker_cannot_reach_another_workers_claim(self):
        self.client.force_login(self.other_worker)
        claim = Claim.objects.get(claim_id="CLM-1021")
        for name in ("claim", "claim_review"):
            self.assertEqual(self.client.get(reverse(name, args=[claim.pk])).status_code, 403, name)
        self.assertEqual(self.client.get(reverse("queue")).context["claims"], [])
        self.assertEqual(self.client.get(reverse("help_list")).context["requests"], [])

    def test_anonymous_users_are_sent_to_login_everywhere(self):
        self.client.logout()
        for url, _, _ in self.routes:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response.url.startswith(reverse("login")), url)

    def test_403_page_uses_the_site_layout(self):
        self.client.force_login(self.dan)
        response = self.client.get(reverse("queue"))
        self.assertContains(response, "You do not have access to this page", status_code=403)
        self.assertContains(response, "Demo data only. Do not enter real patient information.", status_code=403)

    def test_sidebar_lists_only_the_roles_own_pages(self):
        worker_links = [item["label"] for item in self.client.get(reverse("queue")).context["nav_items"]]
        self.assertEqual(worker_links, ["My Queue", "Daily Training", "Help Requests", "Case Library", "Skill Passport", "Add Claims"])
        self.client.force_login(self.dan)
        specialist_links = [item["label"] for item in self.client.get(reverse("help_list")).context["nav_items"]]
        self.assertEqual(specialist_links, ["Help Requests", "Case Library", "Skill Passport"])

    def test_each_role_lands_on_its_own_page(self):
        self.assertRedirects(self.client.get(reverse("home")), reverse("queue"))
        self.client.force_login(self.dan)
        self.assertRedirects(self.client.get(reverse("home")), reverse("help_list"))
