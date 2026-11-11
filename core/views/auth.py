from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from ..context_processors import nav_for
from ..forms import LoginForm


class Login(LoginView):
    template_name = "core/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, show_demo_hint=settings.DEBUG)


@login_required
def home(request):
    """Send each role to its landing page: the first link in its sidebar."""
    links = nav_for(request.user)
    if not links:
        raise PermissionDenied
    return redirect(links[0]["url"])
