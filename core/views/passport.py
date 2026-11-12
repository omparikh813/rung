from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from ..decorators import role_required
from ..organizations import is_reviewer, organization_of
from ..models import Role
from ..skills import passport as build_passport


def workers(organization):
    """The workers in one organization."""
    return (
        get_user_model()
        .objects.filter(profile__role=Role.WORKER, profile__organization=organization)
        .order_by("first_name", "username")
    )


@role_required(Role.WORKER, Role.SPECIALIST)
def passport(request, username=None):
    """A worker sees their own Skill Passport. A specialist can see any worker's in their organization."""
    is_specialist = is_reviewer(request.user)
    team = workers(organization_of(request.user))
    if username is None:
        if not is_specialist:
            worker = request.user
        else:
            first = team.first()
            if first is None:
                return render(request, "core/passport.html", {"workers": []})
            return redirect("passport_user", username=first.username)
    else:
        worker = get_object_or_404(team, username=username)
        if not is_specialist and worker != request.user:
            raise PermissionDenied
    context = {"worker": worker, "workers": team if is_specialist else [], **build_passport(worker)}
    return render(request, "core/passport.html", context)
