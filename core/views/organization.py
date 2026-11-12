"""The Organization Admin's dashboard: overview, employees, performance, settings, and subscription.

This is a demo. There are no prices or payments, and nothing here creates an organization.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..decorators import role_required
from ..models import DONE_STATUSES, Claim, HelpRequest, RequestStatus, Role, SkillRecord
from ..organizations import FEATURES, organization_of, tier_for
from ..skills import passport

SECTIONS = [
    ("overview", "Overview", "building-2"),
    ("employees", "Employees", "users"),
    ("performance", "Performance", "trending-up"),
    ("settings", "Settings", "settings"),
    ("subscription", "Subscription", "file-signature"),
]


def members(organization):
    """Everyone in the organization, active first, then by role and name."""
    people = list(
        get_user_model()
        .objects.filter(profile__organization=organization)
        .select_related("profile")
        .order_by("-is_active", "profile__role", "first_name", "username")
    )
    order = {Role.ADMIN: 0, Role.SPECIALIST: 1, Role.WORKER: 2}
    people.sort(key=lambda user: (not user.is_active, order.get(user.profile.role, 3), user.first_name or user.username))
    return people


def performance_rows(organization):
    """Each worker's progress, for spotting who is ready for a promotion."""
    rows = []
    for user in members(organization):
        if user.profile.role != Role.WORKER or not user.is_active:
            continue
        data = passport(user)
        training = SkillRecord.objects.filter(worker=user).aggregate(correct=Sum("training_correct"), total=Sum("training_attempts"))
        rows.append(
            {
                "user": user,
                "accuracy": data["accuracy"],
                "scored": data["scored"],
                "completed": data["completed"],
                "minimal": next(tile["value"] for tile in data["tiles"] if tile["label"] == "Areas at Minimal help"),
                "training_correct": training["correct"] or 0,
                "training_total": training["total"] or 0,
                "ready": data["ready"],
                "goals": data["goals"],
            }
        )
    rows.sort(key=lambda row: (not row["ready"], -(row["accuracy"] or 0)))
    return rows


@role_required(Role.ADMIN)
def organization(request):
    org = organization_of(request.user)
    section = request.GET.get("section", "overview")
    if section not in dict((key, label) for key, label, _ in SECTIONS):
        section = "overview"
    people = members(org)
    active = [user for user in people if user.is_active]
    counts = {role: sum(user.profile.role == role for user in active) for role in Role.values}
    tier, plan = tier_for(org.seat_limit)
    claims = Claim.objects.filter(organization=org)
    rows = performance_rows(org) if section in ("overview", "performance") else []
    scored = [row for row in rows if row["accuracy"] is not None]
    context = {
        "org": org,
        "section": section,
        "sections": SECTIONS,
        "people": people,
        "roles": Role.choices,
        "tiles": [
            {"icon": "users", "label": "Active employees", "value": len(active)},
            {"icon": "badge-plus", "label": f"Seats left of {org.seat_limit}", "value": org.seats_left},
            {"icon": "graduation-cap", "label": "Workers", "value": counts[Role.WORKER]},
            {"icon": "shield-check", "label": "Specialists", "value": counts[Role.SPECIALIST]},
            {"icon": "user-cog", "label": "Admins", "value": counts[Role.ADMIN]},
        ],
        "seat_percent": round(100 * len(active) / org.seat_limit) if org.seat_limit else 0,
        "tier": tier,
        "plan": plan,
        "features": [(label, key in org.features) for key, label in FEATURES.items()],
        "rows": rows,
        "ready_count": sum(row["ready"] for row in rows),
        "stats": {
            "claims_done": claims.filter(work_status__in=DONE_STATUSES).count(),
            "claims_open": claims.exclude(work_status__in=DONE_STATUSES).count(),
            "open_requests": HelpRequest.objects.filter(claim__organization=org, status=RequestStatus.OPEN).count(),
            "average_accuracy": round(sum(row["accuracy"] for row in scored) / len(scored)) if scored else None,
        },
    }
    return render(request, "core/organization.html", context)


@require_POST
@role_required(Role.ADMIN)
def employee_update(request, user_id):
    """Change an employee's role, or deactivate or reactivate them. Admins never change themselves here."""
    org = organization_of(request.user)
    employee = get_object_or_404(get_user_model().objects.select_related("profile"), pk=user_id, profile__organization=org)
    if employee == request.user:
        raise PermissionDenied
    name = employee.first_name or employee.username
    action = request.POST.get("action")
    back = request.POST.get("section", "employees")

    if action == "role":
        role = request.POST.get("role")
        if role not in Role.values:
            raise PermissionDenied
        before = employee.profile.role
        employee.profile.role = role
        employee.profile.save(update_fields=["role"])
        if before == Role.WORKER and role == Role.SPECIALIST:
            messages.success(request, f"{name} was promoted to Specialist.")
        elif before != role:
            messages.success(request, f"{name} is now {Role(role).label}.")
    elif action == "deactivate":
        employee.is_active = False
        employee.save(update_fields=["is_active"])
        messages.success(request, f"{name} was deactivated and can no longer sign in. Their seat is free.")
    elif action == "reactivate":
        if org.seats_left == 0:
            messages.error(request, f"All {org.seat_limit} seats are in use, so {name} cannot be reactivated.")
        else:
            employee.is_active = True
            employee.save(update_fields=["is_active"])
            messages.success(request, f"{name} was reactivated.")
    else:
        raise PermissionDenied
    if back not in [key for key, _, _ in SECTIONS]:
        back = "employees"
    return redirect(f"{reverse('organization')}?section={back}")
