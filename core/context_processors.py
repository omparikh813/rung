"""Values every template needs: the user's role and the sidebar links."""

from django.urls import reverse

from .decorators import user_role
from .organizations import is_reviewer, organization_of
from .models import HelpRequest, RequestStatus, Role

# Sidebar links: URL name -> label, icon, and the URL names that keep the link highlighted.
LINKS = {
    "queue": ("My Queue", "list-checks", ("claim",)),
    "training": ("Daily Training", "graduation-cap", ("training_exercise",)),
    "help_list": ("Help Requests", "life-buoy", ("help_detail",)),
    "library": ("Case Library", "library", ("library_detail", "library_edit")),
    "passport": ("Skill Passport", "award", ("passport_user",)),
    "upload": ("Add Claims", "plus", ("claim_new",)),
}

# Each role's sidebar, in order. The first link is the role's landing page.
NAV = {
    Role.WORKER: ["queue", "training", "help_list", "library", "passport", "upload"],
    Role.SPECIALIST: ["help_list", "queue", "library", "passport", "upload"],
    Role.ADMIN: ["help_list", "queue", "library", "passport", "upload"],
}


def open_help_requests(user):
    """Open requests: all of their organization's for a specialist, their own for a worker."""
    requests = HelpRequest.objects.filter(status=RequestStatus.OPEN)
    if is_reviewer(user):
        return requests.filter(claim__organization=organization_of(user))
    return requests.filter(worker=user)


def nav_for(user, current=""):
    links = []
    for name in NAV.get(user_role(user), []):
        label, icon, also = LINKS[name]
        links.append({"name": name, "url": reverse(name), "label": label, "icon": icon, "active": current in (name, *also)})
    for link in links:
        if link["name"] == "help_list":
            link["count"] = open_help_requests(user).count()
    return links


def rung(request):
    if not request.user.is_authenticated:
        return {"role": "", "nav_items": []}
    current = request.resolver_match.url_name if request.resolver_match else ""
    return {"role": user_role(request.user), "nav_items": nav_for(request.user, current)}
