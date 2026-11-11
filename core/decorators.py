from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def user_role(user):
    profile = getattr(user, "profile", None)
    return profile.role if profile else ""


def role_required(*roles):
    """Allow only signed in users with one of the given roles. Everyone else gets a 403."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if user_role(request.user) not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
