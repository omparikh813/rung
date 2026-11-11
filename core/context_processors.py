"""Values every template needs: the user's role and the sidebar links."""

from django.urls import reverse

from .decorators import user_role
from .models import Role

# Sidebar links in display order: URL name, label, icon, roles, and the URL names
# that keep the link highlighted. A role's first link is its landing page.
NAV = [
    ("queue", "My Queue", "list-checks", {Role.WORKER}, ("claim",)),
]


def nav_for(user, current=""):
    role = user_role(user)
    return [
        {"url": reverse(name), "label": label, "icon": icon, "active": current in (name, *also)}
        for name, label, icon, roles, also in NAV
        if role in roles
    ]


def rung(request):
    if not request.user.is_authenticated:
        return {"role": "", "nav_items": []}
    current = request.resolver_match.url_name if request.resolver_match else ""
    return {"role": user_role(request.user), "nav_items": nav_for(request.user, current)}
