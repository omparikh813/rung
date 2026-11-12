from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from ..ai import latest_review
from ..claims import save_claim_form, visible_claims
from ..decorators import role_required
from ..organizations import is_reviewer, organization_of
from .. import payer
from ..forms import ClaimForm, ResolutionForm
from ..models import Category, ClaimEvent, EventAction, HelpRequest, Outcome, RequestStatus, Role, WorkStatus
from .workspace import workspace_context

# The claim status each outcome leaves behind.
OUTCOME_STATUS = {
    Outcome.RETURNED: WorkStatus.READY,
    Outcome.SUBMITTED: WorkStatus.SUBMITTED,
    Outcome.WRITE_OFF: WorkStatus.CLOSED,
    Outcome.APPEAL: WorkStatus.CLOSED,
}


def ai_categories(claim):
    """The categories the latest AI review flagged, for the specialist inbox."""
    review = latest_review(claim)
    if review is None:
        return "Not checked"
    found = dict.fromkeys(issue["category"] for issue in review.result_json["issues"] if issue["category"])
    return ", ".join(Category(category).label for category in found) or "No issues found"


@role_required(Role.WORKER, Role.SPECIALIST)
def help_list(request):
    """A worker sees their own requests. A specialist sees every request in their organization, open ones first."""
    is_specialist = is_reviewer(request.user)
    requests = HelpRequest.objects.select_related("worker", "specialist").prefetch_related("claim__reviews")
    if is_specialist:
        requests = requests.filter(claim__organization=organization_of(request.user))
    else:
        requests = requests.filter(worker=request.user)
    rows = [
        {
            "pk": item.pk,
            "claim_pk": item.claim_id,
            "claim_id": item.claim.claim_id,
            "payer": item.claim.payer_name,
            "worker": item.worker.get_full_name() or item.worker.username,
            "question": item.question,
            "status": item.status,
            "created_at": item.created_at,
            "resolution_note": item.resolution_note,
            "outcome": item.get_outcome_display() if item.outcome else "",
            "ai_category": ai_categories(item.claim) if is_specialist else "",
        }
        for item in requests
    ]
    open_count = sum(row["status"] == RequestStatus.OPEN for row in rows)
    tiles = [
        {"icon": "clock", "label": "Open", "value": open_count},
        {"icon": "circle-check", "label": "Resolved", "value": len(rows) - open_count},
    ]
    template = "core/help_inbox.html" if is_specialist else "core/help_list.html"
    return render(request, template, {"requests": rows, "open_count": open_count, "tiles": tiles})


def case_entry_start(claim):
    """Case Library fields filled in from the claim. Never patient names, member IDs, or dates."""
    codes = [claim.cpt_1, claim.cpt_2, claim.icd10_primary, claim.icd10_secondary]
    review = latest_review(claim)
    categories = [issue["category"] for issue in review.result_json["issues"]] if review else []
    return {
        "payer_name": claim.payer_name,
        "codes": ", ".join(code for code in codes if code),
        "denial_code": claim.denial_code,
        "category": next((category for category in categories if category), ""),
    }


@role_required(Role.SPECIALIST)
def help_detail(request, pk):
    help_request = get_object_or_404(
        HelpRequest.objects.select_related("worker", "specialist"), pk=pk, claim__organization=organization_of(request.user)
    )
    claim = get_object_or_404(visible_claims(), pk=help_request.claim_id)
    is_open = help_request.status == RequestStatus.OPEN

    if request.method == "POST":
        if not is_open:
            raise PermissionDenied
        form = ClaimForm(request.POST, instance=claim)
        resolution = ResolutionForm(request.POST, prefix="res")
        if form.is_valid() and resolution.is_valid():
            saved_entry = resolve(request, help_request, claim, form, resolution)
            note = " The fix was saved to the Case Library." if saved_entry else ""
            messages.success(request, f"Request for {claim.claim_id} resolved.{note}")
            return redirect("help_list")
        messages.error(request, "Some fields need a fix before this can be resolved.")
    else:
        form = ClaimForm(instance=claim, read_only=not is_open)
        resolution = ResolutionForm(prefix="res", initial=case_entry_start(claim))

    context = workspace_context(claim, form)
    context.update(help_request=help_request, resolution=resolution, editable=is_open)
    return render(request, "core/help_detail.html", context)


@transaction.atomic
def resolve(request, help_request, claim, form, resolution):
    """Save the specialist's changes, set the claim status from the outcome, and close the request."""
    data = resolution.cleaned_data
    outcome = Outcome(data["outcome"])
    save_claim_form(form, request.user)
    claim.work_status = OUTCOME_STATUS[outcome]
    claim.help_request_open = False
    claim.save(update_fields=["work_status", "help_request_open", "updated_at"])
    ClaimEvent.objects.create(
        claim=claim,
        user=request.user,
        action=EventAction.RESOLVE,
        old_value=outcome.label,
        new_value=data["resolution_note"],
    )
    help_request.status = RequestStatus.RESOLVED
    help_request.specialist = request.user
    help_request.outcome = outcome
    help_request.resolution_note = data["resolution_note"]
    help_request.resolved_at = timezone.now()
    help_request.save()
    if outcome == Outcome.SUBMITTED:
        payer.respond(claim, request.user)  # A claim a specialist fixed and submitted is paid.
    if data["save_to_library"]:
        resolution.case_entry(
            source_request=help_request, created_by=request.user, organization=claim.organization
        ).save()
    return data["save_to_library"]
