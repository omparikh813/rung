"""The simulated payer. In this demo nothing is sent to an insurance company.

When a claim is submitted, this module answers the way a payer would: it pays a claim
that is correct and denies one that is not, with a standard denial code and reason.
"""

from .ai import latest_review
from .claims import days_left_to_file, filing_limits
from .models import (
    Category,
    Claim,
    ClaimEvent,
    ClaimStatus,
    EventAction,
    FinalAction,
    RequestStatus,
    WorkStatus,
)
from .reviews import issue_cards
from .skills import is_correct

# A standard denial code and reason for each skill category.
DENIALS = {
    Category.ELIGIBILITY: ("CO-31", "Patient cannot be identified as our insured"),
    Category.PRIOR_AUTH: ("CO-197", "Precertification/authorization/notification absent"),
    Category.CODE_MATCHING: ("CO-11", "The diagnosis is inconsistent with the procedure"),
    Category.MODIFIERS: ("CO-4", "The procedure code is inconsistent with the modifier used, or a required modifier is missing"),
    Category.DOCUMENTATION: ("CO-16", "Claim lacks information needed for adjudication"),
    Category.FILING_RULES: ("CO-16", "Claim lacks information needed for adjudication"),
}  # fmt: skip
TIMELY_FILING = ("CO-29", "The time limit for filing has expired")
DUPLICATE = ("CO-18", "Exact duplicate claim/service")
GENERAL = ("CO-16", "Claim lacks information needed for adjudication")


def has_earlier_duplicate(claim):
    """Whether the same patient already has a claim for the same date and CPT code."""
    return Claim.objects.filter(
        patient_first=claim.patient_first,
        patient_last=claim.patient_last,
        patient_dob=claim.patient_dob,
        date_of_service=claim.date_of_service,
        cpt_1=claim.cpt_1,
        pk__lt=claim.pk,
    ).exists()


def denial_for(claim, category):
    """The denial code and reason for a claim the payer will not pay."""
    days_left = days_left_to_file(claim, filing_limits())
    if days_left is not None and days_left < 0:
        return TIMELY_FILING
    if has_earlier_duplicate(claim):
        return DUPLICATE
    if claim.denial_code:  # Denied before for a reason that still stands.
        return claim.denial_code, claim.denial_reason
    return DENIALS.get(category, GENERAL)


def judge(claim):
    """Decide the payer's answer. Returns (paid, category) or None if there is nothing to judge by.

    A claim a specialist has resolved is paid. A claim with an answer key is judged by it.
    Any other claim is judged by its latest AI review: no open issues means paid.
    """
    if claim.help_requests.filter(status=RequestStatus.RESOLVED).exists():
        return True, ""
    if claim.expected_action:
        return is_correct(claim, FinalAction.SUBMIT), claim.expected_category
    review = latest_review(claim)
    if review is None:
        return None
    open_issues = [card for card in issue_cards(claim, review) if not card["addressed"]]
    return not open_issues, open_issues[0]["category"] if open_issues else ""


def respond(claim, user):
    """Answer a submitted claim at once. Returns "paid", "denied", or "" if it stays Submitted."""
    claim = Claim.objects.get(pk=claim.pk)  # With the answer key, which views never load.
    verdict = judge(claim)
    if verdict is None:
        return ""
    paid, category = verdict
    if paid:
        claim.work_status = WorkStatus.PAID
        claim.save(update_fields=["work_status", "updated_at"])
        ClaimEvent.objects.create(claim=claim, user=None, action=EventAction.PAYER, new_value="Paid")
        return "paid"
    code, reason = denial_for(claim, category)
    claim.work_status = WorkStatus.DENIED
    claim.status = ClaimStatus.DENIED
    claim.denial_code, claim.denial_reason = code, reason
    claim.save(update_fields=["work_status", "status", "denial_code", "denial_reason", "updated_at"])
    ClaimEvent.objects.create(claim=claim, user=None, action=EventAction.PAYER, new_value=f"Denied: {code} {reason}")
    return "denied"
