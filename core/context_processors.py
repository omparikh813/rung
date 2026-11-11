"""Values every template needs: the user's role and the sidebar links."""


def rung(request):
    user = request.user
    profile = getattr(user, "profile", None) if user.is_authenticated else None
    return {"role": profile.role if profile else "", "nav_items": []}
