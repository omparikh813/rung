import os

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..ai import AIError, claim_version_hash, latest_review
from ..claims import FIELD_GROUPS, claim_history, save_claim_form, visible_claims
from ..decorators import role_required
from ..forms import ClaimForm
from ..models import ClaimEvent, EventAction, FinalAction, HelpLevel, Role, WorkStatus
from ..reviews import field_hints, issue_cards, open_high_confidence, run_review
from ..skills import PLAIN_NAMES, score_claim

CLOSE_REASONS = [("duplicate", "Duplicate"), ("not_billable", "Not billable"), ("other", "Other")]


def worker_claim(request, pk):
    """The worker's own claim, or a 403 for anyone else's."""
    claim = get_object_or_404(visible_claims(), pk=pk)
    if claim.assigned_to_id != request.user.pk:
        raise PermissionDenied
    return claim


def workspace_context(claim, form, *, fade_help=True, review_error=False):
    """Everything the claim form and the help panel need. The answer key is never part of it."""
    review = latest_review(claim)
    cards = issue_cards(claim, review, fade_help)
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
def claim(request, pk):
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
    messages.success(request, f"{claim.claim_id} submitted.")
    return redirect("queue")


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


@role_required(Role.WORKER)
def claim_review(request, pk):
    """The help panel. GET runs the review if needed. POST (Re-check) saves the form first."""
    claim = worker_claim(request, pk)
    form = ClaimForm(instance=claim, read_only=not claim.is_open)
    form_error = review_error = False
    if request.method == "POST" and claim.is_open:
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
    context.update(editable=claim.is_open, form_error=form_error)
    return render(request, "core/partials/review_response.html", context)


@require_POST
@role_required(Role.WORKER)
def claim_answer(request, pk, index):
    """Show answer: reveal one issue's answer and mark the claim as assisted."""
    claim = worker_claim(request, pk)
    review = latest_review(claim)
    issues = review.result_json["issues"] if review else []
    if index >= len(issues):
        raise Http404
    already = claim.events.filter(
        action=EventAction.ANSWER_SHOWN, new_value=str(index), created_at__gt=review.created_at
    ).exists()
    if not already:
        ClaimEvent.objects.create(
            claim=claim,
            user=request.user,
            action=EventAction.ANSWER_SHOWN,
            field=issues[index]["field"][:50],
            new_value=str(index),
        )
    return render(request, "core/partials/answer.html", {"issue": issues[index]})
