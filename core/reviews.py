"""Turns a stored AI review into what the Claim Workspace shows."""

import re

from .ai import latest_review, review_claim
from .claims import ANSWER_KEY_FIELDS, CSV_COLUMNS, FORM_FIELDS, field_label
from .models import Category, ClaimEvent, EventAction, WorkStatus


# Every claim field name with an underscore, such as icd10_primary, denial_code, or ndc_code.
# Longest first, so modifiers_1 is not cut short. The answer key is left out.
_NAMES = [name for name in CSV_COLUMNS if "_" in name and name not in ANSWER_KEY_FIELDS]
_FIELD_NAME = re.compile(r"\b(" + "|".join(sorted(_NAMES, key=len, reverse=True)) + r")\b")


def plain_fields(text):
    """Swap field names the AI used, such as icd10_primary, for the labels a worker sees on the form."""
    return _FIELD_NAME.sub(lambda match: field_label(match.group(1)), text or "")


def run_review(claim, user):
    """Review the claim. A new review updates the claim status and is logged."""
    before = latest_review(claim)
    review = review_claim(claim)
    if before is None or review.pk != before.pk:
        issues = review.result_json["issues"]
        if claim.is_open:
            claim.work_status = WorkStatus.NEEDS_FIX if issues else WorkStatus.READY
            claim.save(update_fields=["work_status", "updated_at"])
        found = f"{len(issues)} issue{'s' if len(issues) != 1 else ''} found" if issues else "No issues found"
        ClaimEvent.objects.create(claim=claim, user=user, action=EventAction.CHECK, new_value=found)
    return review


def issue_cards(claim, review):
    """One card per AI issue. Real claims always get full help: the explanation, the fix, and its source.

    Help that fades with skill belongs to Daily Training, not to real claims.
    """
    if review is None:
        return []
    since = claim.events.filter(created_at__gt=review.created_at)
    edited = set(since.filter(action=EventAction.EDIT).values_list("field", flat=True))
    cards = []
    for index, issue in enumerate(review.result_json["issues"]):
        fields = [name for name in re.split(r"[^a-z0-9_]+", issue["field"].lower()) if name in FORM_FIELDS]
        cards.append(
            {
                **issue,
                "index": index,
                "fields": fields,
                "open_fields": [name for name in fields if name not in edited],
                "category_label": Category(issue["category"]).label if issue["category"] else "Claim",
                "text": plain_fields(issue["full"]),
                "minimal": plain_fields(issue["minimal"]),
                # An issue counts as handled once every field it names has been changed since the review.
                "addressed": bool(fields) and all(name in edited for name in fields),
            }
        )
    return cards


def field_hints(cards):
    """The issue text to show under each flagged field that has not been changed since the review."""
    hints = {}
    for card in cards:
        for name in card["open_fields"]:
            hints[name] = f"{hints[name]} {card['text']}" if name in hints else card["text"]
    return hints


def open_high_confidence(cards):
    return [card for card in cards if card["confidence"] == "high" and not card["addressed"]]
