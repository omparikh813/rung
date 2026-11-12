"""The simulated payer. In this demo nothing is sent to an insurance company.

When a claim is submitted, this module answers the way a payer would: it pays a claim
that is correct and denies one that is not, with a standard denial code and reason.
"""

from .ai import latest_review
from .claims import days_left_to_file, field_label, filing_limits
from .models import (
    CaseEntry,
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

# The skill area each denial code points to, for claims with no answer key.
DENIAL_CATEGORIES = {
    "CO-4": Category.MODIFIERS,
    "CO-11": Category.CODE_MATCHING,
    "CO-16": Category.DOCUMENTATION,
    "CO-18": Category.FILING_RULES,
    "CO-22": Category.ELIGIBILITY,
    "CO-27": Category.ELIGIBILITY,
    "CO-29": Category.FILING_RULES,
    "CO-31": Category.ELIGIBILITY,
    "CO-50": Category.DOCUMENTATION,
    "CO-197": Category.PRIOR_AUTH,
}

# Fields that identify the patient. A library entry says they changed, never what to.
PRIVATE_FIELDS = {
    "patient_first", "patient_last", "patient_dob", "patient_sex", "member_id", "date_of_service",
    "eligibility_note", "prior_auth_number", "referral_number",
}  # fmt: skip


def has_earlier_duplicate(claim):
    """Whether the same patient already has a claim for the same date and CPT code."""
    return Claim.objects.filter(
        organization=claim.organization,
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
        was_denied = claim.status == ClaimStatus.DENIED and bool(claim.denial_code)
        claim.work_status = WorkStatus.PAID
        claim.save(update_fields=["work_status", "updated_at"])
        ClaimEvent.objects.create(claim=claim, user=None, action=EventAction.PAYER, new_value="Paid")
        if was_denied:
            library_entry_from_insurer(claim)
        return "paid"
    code, reason = denial_for(claim, category)
    claim.work_status = WorkStatus.DENIED
    claim.status = ClaimStatus.DENIED
    claim.denial_code, claim.denial_reason = code, reason
    claim.save(update_fields=["work_status", "status", "denial_code", "denial_reason", "updated_at"])
    ClaimEvent.objects.create(claim=claim, user=None, action=EventAction.PAYER, new_value=f"Denied: {code} {reason}")
    return "denied"


def fix_lines(claim):
    """What changed to get a denied claim paid, one line per field, with no patient details.

    Counts the edits since the insurer first denied the claim, or every edit if it arrived denied.
    """
    first_denial = claim.events.filter(action=EventAction.PAYER, new_value__startswith="Denied").order_by("created_at", "id").first()
    edits = claim.events.filter(action=EventAction.EDIT).order_by("created_at", "id")
    if first_denial:
        edits = edits.filter(created_at__gte=first_denial.created_at)
    changes = {}
    for edit in edits:
        before = changes[edit.field][0] if edit.field in changes else edit.old_value
        changes[edit.field] = (before, edit.new_value)
    lines = []
    for field, (before, after) in changes.items():
        if before == after:
            continue
        label = field_label(field)
        if field in PRIVATE_FIELDS:
            lines.append(f"{label} was {'added' if not before else 'corrected'}.")
        elif after:
            lines.append(f"{label} changed to {after}.")
        else:
            lines.append(f"{label} was cleared.")
    return lines, [field_label(field) for field in changes]


def library_entry_from_insurer(claim):
    """Save a Case Library entry for a claim the insurer denied and then paid once it was fixed."""
    if CaseEntry.objects.filter(source_request__claim=claim).exists():
        return None  # A specialist already wrote this one up.
    lines, labels = fix_lines(claim)
    if not lines:
        return None
    code, reason = claim.denial_code, claim.denial_reason
    category = claim.expected_category if claim.expected_category in Category.values else DENIAL_CATEGORIES.get(code, Category.DOCUMENTATION)
    codes = [c for c in (claim.cpt_1, claim.cpt_2, claim.icd10_primary, claim.icd10_secondary) if c]
    checked = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + labels[-1]
    return CaseEntry.objects.create(
        title=f"{Category(category).label}: {claim.payer_name} denial {code}",
        category=category,
        payer_name=claim.payer_name,
        codes=", ".join(codes),
        denial_code=code,
        problem=f"{claim.payer_name} denied the claim with {code}: {reason}.",
        fix=" ".join(lines) + " The claim was resubmitted and the insurer paid it.",
        tip=f"Check {checked} before the first submission to avoid a {code} denial.",
        from_insurer=True,
        source_claim=claim,
        organization=claim.organization,
    )
