from django.db.models import Q
from django.shortcuts import render

from ..claims import days_left_to_file, days_left_tone, filing_limits
from ..decorators import role_required
from ..models import DONE_STATUSES, OPEN_STATUSES, Claim, Role, WorkStatus

# Tab key, label, statuses, and the sentence shown when the tab is empty.
TABS = [
    ("open", "Open", OPEN_STATUSES, "Claims that are new, denied, or ready to work will appear here."),
    ("needs_fix", "Needs Fix", [WorkStatus.NEEDS_FIX], "Claims where the AI review found something to fix will appear here."),
    ("denied", "Denied", [WorkStatus.DENIED], "Claims a payer has denied will appear here until you check them."),
    ("waiting", "Waiting on Specialist", [WorkStatus.WAITING], "Claims you have sent to a specialist will appear here."),
    ("done", "Done", DONE_STATUSES, "Claims you have submitted or closed will appear here."),
]  # fmt: skip


@role_required(Role.WORKER)
def queue(request):
    claims = Claim.objects.filter(assigned_to=request.user)
    statuses = list(claims.values_list("work_status", flat=True))
    tabs = [
        {"key": key, "label": label, "count": sum(status in group for status in statuses), "empty": empty}
        for key, label, group, empty in TABS
    ]
    current = next((tab for tab in tabs if tab["key"] == request.GET.get("tab")), tabs[0])
    group = next(group for key, _, group, _ in TABS if key == current["key"])

    query = request.GET.get("q", "").strip()
    rows = claims.filter(work_status__in=group).prefetch_related("reviews")
    if query:
        rows = rows.filter(Q(claim_id__icontains=query) | Q(patient_last__icontains=query))

    limits = filing_limits()
    rows = list(rows)
    for claim in rows:
        claim.days_left = None if claim.work_status in DONE_STATUSES else days_left_to_file(claim, limits)
        claim.days_tone = days_left_tone(claim.days_left)
        reviews = claim.reviews.all()
        claim.open_issues = len(reviews[0].result_json.get("issues", [])) if reviews else None
    # Lowest days left first. Claims with no deadline go last.
    rows.sort(key=lambda claim: (claim.days_left is None, claim.days_left or 0, claim.pk))

    context = {"tabs": tabs, "current": current, "query": query, "claims": rows, "open_count": tabs[0]["count"]}
    template = "core/partials/queue_table.html" if request.headers.get("HX-Request") else "core/queue.html"
    return render(request, template, context)
