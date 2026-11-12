"""Values every template needs: the user's role and the sidebar links."""

from django.urls import reverse

from .decorators import user_role
from .models import HelpRequest, RequestStatus, Role

# Sidebar links in display order: URL name, label, icon, roles, and the URL names
# that keep the link highlighted. A role's first link is its landing page.
NAV = [
    ("queue", "My Queue", "list-checks", {Role.WORKER}, ("claim",)),
    ("help_list", "Help Requests", "life-buoy", {Role.WORKER, Role.SPECIALIST}, ("help_detail",)),
    ("library", "Case Library", "library", {Role.WORKER, Role.SPECIALIST}, ("library_detail", "library_edit")),
    ("passport", "Skill Passport", "award", {Role.WORKER, Role.SPECIALIST}, ("passport_user",)),
    ("upload", "Add Claims", "plus", {Role.WORKER}, ("claim_new",)),
]


def open_help_requests(user):
    """Open requests: all of them for a specialist, their own for a worker."""
    requests = HelpRequest.objects.filter(status=RequestStatus.OPEN)
    return requests if user_role(user) == Role.SPECIALIST else requests.filter(worker=user)


def nav_for(user, current=""):
    role = user_role(user)
    links = [
        {"name": name, "url": reverse(name), "label": label, "icon": icon, "active": current in (name, *also)}
        for name, label, icon, roles, also in NAV
        if role in roles
    ]
    for link in links:
        if link["name"] == "help_list":
            link["count"] = open_help_requests(user).count()
    return links


def rung(request):
    if not request.user.is_authenticated:
        return {"role": "", "nav_items": []}
    current = request.resolver_match.url_name if request.resolver_match else ""
    return {"role": user_role(request.user), "nav_items": nav_for(request.user, current)}
