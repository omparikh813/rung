import os

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..ai import AIError, claim_version_hash, latest_review
from ..claims import FIELD_GROUPS, claim_history, next_claim_id, save_claim_form, similar_cases, visible_claims
from ..decorators import role_required
from ..organizations import is_reviewer, organization_of
from ..forms import ClaimForm, NewClaimForm
from .. import payer
from ..models import CaseEntry, ClaimEvent, EventAction, FinalAction, HelpLevel, HelpRequest, RequestStatus, Role, WorkStatus
from ..reviews import field_hints, issue_cards, open_high_confidence, run_review
from ..skills import PLAIN_NAMES, score_claim
from ..x12 import build_837p

CLOSE_REASONS = [("duplicate", "Duplicate"), ("not_billable", "Not billable"), ("other", "Other")]


def worker_claim(request, pk):
    """The worker's own claim, or a 403 for anyone else's."""
    claim = get_object_or_404(visible_claims(), pk=pk)
    if claim.assigned_to_id != request.user.pk:
        raise PermissionDenied
    return claim


def reviewable_claim(request, pk):
    """A claim this user may run checks on, and whether they may change it.

    A worker reaches their own claims. A specialist reaches claims in their organization through a help request.
    """
    if not is_reviewer(request.user):
        claim = worker_claim(request, pk)
        return claim, claim.is_open
    claim = get_object_or_404(visible_claims(), pk=pk, organization=organization_of(request.user))
    requests = claim.help_requests.all()
    if not requests.exists():
        raise PermissionDenied
    return claim, requests.filter(status=RequestStatus.OPEN).exists()


def workspace_context(claim, form, *, review_error=False):
    """Everything the claim form and the help panel need. The answer key is never part of it."""
    review = latest_review(claim)
    cards = issue_cards(claim, review)
    hints = field_hints(cards)
    groups = [
        {
            "title": title,
            "icon": icon,
            "fields": [{"field": form[name], "hint": hints.get(name, "")} for name in fields],
        }
        for title, icon, fields in FIELD_GROUPS
    ]
    return {
        "claim": claim,
        "form": form,
        "groups": groups,
        "review": review,
        "cards": cards,
        "stale": review is not None and review.claim_version_hash != claim_version_hash(claim),
        "review_error": review_error,
        "missing_key": review_error and settings.DEBUG and not os.environ.get("OPENROUTER_API_KEY"),
        "history": claim_history(claim),
        "similar": similar_cases(claim),
    }


def render_workspace(request, claim, form):
    context = workspace_context(claim, form)
    context.update(
        editable=claim.is_open,
        auto_review=claim.is_open and context["review"] is None,
        close_reasons=CLOSE_REASONS,
        confirm_issues=open_high_confidence(context["cards"]) if request.GET.get("confirm") == "submit" else [],
    )
    return render(request, "core/workspace.html", context)


@role_required(Role.WORKER)
def claim_new(request):
    """Create one claim with a form. It is assigned to the worker and checked as soon as it opens."""
    form = NewClaimForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        claim = form.save(commit=False)
        claim.organization = organization_of(request.user)
        claim.claim_id = next_claim_id(claim.organization)
        claim.assigned_to = request.user
        claim.save()
        messages.success(request, f"{claim.claim_id} created. RUNG is checking it now.")
        return redirect("claim", pk=claim.pk)
    if request.method == "POST":
        messages.error(request, "Some fields need a fix before the claim can be created.")
    groups = [
        {"title": title, "icon": icon, "fields": [{"field": form[name], "hint": ""} for name in fields]}
        for title, icon, fields in FIELD_GROUPS
    ]
    return render(request, "core/claim_new.html", {"form": form, "groups": groups})


@role_required(Role.WORKER, Role.SPECIALIST)
def claim(request, pk):
    if is_reviewer(request.user):
        # A specialist works a claim from its help request.
        help_request = (
            HelpRequest.objects.filter(claim_id=pk, claim__organization=organization_of(request.user))
            .order_by("-created_at")
            .first()
        )
        if help_request is None:
            raise PermissionDenied
        return redirect("help_detail", pk=help_request.pk)
    claim = worker_claim(request, pk)
    if request.method != "POST":
        return render_workspace(request, claim, ClaimForm(instance=claim, read_only=not claim.is_open))
    if not claim.is_open:
        raise PermissionDenied

    action = request.POST.get("action", "save")
    if action == "close":
        return close_claim(request, claim)

    form = ClaimForm(request.POST, instance=claim)
    if not form.is_valid():
        messages.error(request, "Some fields need a fix before this can be saved.")
        return render_workspace(request, claim, form)
    changed = save_claim_form(form, request.user)
    if action in ("submit", "submit_confirmed"):
        return submit_claim(request, claim)
    if action == "ask":
        return ask_specialist(request, claim)
    messages.success(request, "Changes saved." if changed else "Nothing to save. No fields were changed.")
    return redirect("claim", pk=claim.pk)


def score_final_action(request, claim, action):
    """Score the worker's first final action. A toast names the category if the help level dropped."""
    improved = score_claim(claim, request.user, action)
    if improved:
        name = PLAIN_NAMES[improved.category][0]
        level = HelpLevel(improved.help_level).label
        messages.add_message(
            request, messages.SUCCESS, f"{name} improved. Help in this category is now {level}.", extra_tags="level"
        )


def submit_claim(request, claim):
    """Submit is simulated: it only changes the claim status."""
    cards = issue_cards(claim, latest_review(claim))
    if open_high_confidence(cards) and request.POST.get("action") != "submit_confirmed":
        return redirect(f"{reverse('claim', args=[claim.pk])}?confirm=submit")
    claim.work_status = WorkStatus.SUBMITTED
    claim.save(update_fields=["work_status", "updated_at"])
    ClaimEvent.objects.create(claim=claim, user=request.user, action=EventAction.SUBMIT)
    score_final_action(request, claim, FinalAction.SUBMIT)
    answer = payer.respond(claim, request.user)
    if answer == "paid" and CaseEntry.objects.filter(source_claim_id=claim.pk, from_insurer=True).exists():
        messages.success(request, f"{claim.claim_id} submitted. The payer paid it, and the fix was added to the Case Library.")
    elif answer == "paid":
        messages.success(request, f"{claim.claim_id} submitted. The payer paid it.")
    elif answer == "denied":
        claim.refresh_from_db(fields=["denial_code", "denial_reason"])
        messages.error(
            request,
            f"{claim.claim_id} was denied by the payer ({claim.denial_code}). It is back in your queue to fix.",
        )
    else:
        messages.success(request, f"{claim.claim_id} submitted.")
    return redirect("queue")


def ask_specialist(request, claim):
    """Send the full case to a specialist. Asking is never discouraged."""
    question = request.POST.get("question", "").strip()
    if not question:
        messages.error(request, "Type a question for the specialist before sending.")
        return redirect("claim", pk=claim.pk)
    HelpRequest.objects.create(claim=claim, worker=request.user, question=question)
    claim.work_status = WorkStatus.WAITING
    claim.help_request_open = True
    claim.save(update_fields=["work_status", "help_request_open", "updated_at"])
    ClaimEvent.objects.create(claim=claim, user=request.user, action=EventAction.ESCALATE, new_value=question)
    score_final_action(request, claim, FinalAction.ESCALATE)
    messages.success(request, "Request sent. A specialist will pick it up.")
    return redirect("claim", pk=claim.pk)


def close_claim(request, claim):
    reason = dict(CLOSE_REASONS).get(request.POST.get("close_reason"))
    if not reason:
        messages.error(request, "Choose a reason before closing the claim.")
        return redirect("claim", pk=claim.pk)
    claim.work_status = WorkStatus.CLOSED
    claim.save(update_fields=["work_status", "updated_at"])
    ClaimEvent.objects.create(claim=claim, user=request.user, action=EventAction.CLOSE, new_value=reason)
    score_final_action(request, claim, FinalAction.CLOSE)
    messages.success(request, f"{claim.claim_id} closed.")
    return redirect("queue")


@role_required(Role.WORKER, Role.SPECIALIST)
def claim_review(request, pk):
    """The help panel. GET runs the review if needed. POST (Re-check) saves the form first."""
    claim, editable = reviewable_claim(request, pk)
    form = ClaimForm(instance=claim, read_only=not editable)
    form_error = review_error = False
    if request.method == "POST" and editable:
        form = ClaimForm(request.POST, instance=claim)
        if form.is_valid():
            save_claim_form(form, request.user)
        else:
            form_error = True
    if not form_error:
        try:
            run_review(claim, request.user)
        except AIError:
            review_error = True
    context = workspace_context(claim, form, review_error=review_error)
    context.update(editable=editable, form_error=form_error)
    return render(request, "core/partials/review_response.html", context)


@role_required(Role.WORKER, Role.SPECIALIST)
def claim_export(request, pk):
    """Download a submitted claim as an ANSI X12 837P file.

    A worker can export their own claims. A specialist can export any worker's in their organization.
    """
    claim = get_object_or_404(visible_claims(), pk=pk, organization=organization_of(request.user))
    if not is_reviewer(request.user) and claim.assigned_to_id != request.user.pk:
        raise PermissionDenied
    if not claim.events.filter(action=EventAction.SUBMIT).exists():
        raise Http404("Only submitted claims can be exported.")
    response = HttpResponse(build_837p(claim), content_type="text/plain; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{claim.claim_id}_837P.txt"'
    return response
