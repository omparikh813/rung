from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.decorators import role_required
from core.models import Role
from core.tests.base import PASSWORD, RoleTestCase, make_user

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
        self.assertContains(response, "rung_logo.png")

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

    def test_home_needs_a_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_user_without_a_role_gets_403(self):
        self.client.force_login(make_user("nobody", role=""))
        self.assertEqual(self.client.get(reverse("home")).status_code, 403)
