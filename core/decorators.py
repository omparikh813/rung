from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Role
from .organizations import organization_of


def user_role(user):
    profile = getattr(user, "profile", None)
    return profile.role if profile else ""


def role_required(*roles):
    """Allow only signed in users with one of the given roles. Everyone else gets a 403.

    An admin can do everything a specialist can, so a view open to specialists is open to admins.
    A user who does not belong to an organization gets a 403 everywhere.
    """
    allowed = set(roles) | ({Role.ADMIN} if Role.SPECIALIST in roles else set())

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if user_role(request.user) not in allowed or organization_of(request.user) is None:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
