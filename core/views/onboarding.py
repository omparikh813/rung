"""Start Using RUNG: the organization onboarding steps, as a demo.

Nothing here is saved. Creating organizations waits until RUNG's database is set up.
"""

import json

from django.shortcuts import render
from django.views.decorators.http import require_GET

from ..models import OrganizationType
from ..organizations import DIRECTORY, SEAT_RANGES, TIERS


@require_GET
def start(request):
    sizes = [{"range": seats, "tier": name, "plan": plan} for seats, (_, name, plan) in zip(SEAT_RANGES, TIERS)]
    context = {
        # Escaped by the template, so it is safe inside the x-data attribute.
        "directory_json": json.dumps(DIRECTORY),
        "types": OrganizationType.choices,
        "sizes": sizes,
        "steps": ["Your account", "Your organization", "Team size", "Review"],
    }
    return render(request, "core/start.html", context)
