from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from ..decorators import role_required, user_role
from ..models import Role
from ..skills import passport as build_passport


def workers():
    return get_user_model().objects.filter(profile__role=Role.WORKER).order_by("first_name", "username")


@role_required(Role.WORKER, Role.SPECIALIST)
def passport(request, username=None):
    """A worker sees their own Skill Passport. A specialist can see any worker's."""
    is_specialist = user_role(request.user) == Role.SPECIALIST
    if username is None:
        if not is_specialist:
            worker = request.user
        else:
            first = workers().first()
            if first is None:
                return render(request, "core/passport.html", {"workers": []})
            return redirect("passport_user", username=first.username)
    else:
        worker = get_object_or_404(workers(), username=username)
        if not is_specialist and worker != request.user:
            raise PermissionDenied
    context = {"worker": worker, "workers": workers() if is_specialist else [], **build_passport(worker)}
    return render(request, "core/passport.html", context)
