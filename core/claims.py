"""Helpers for working with claims: CSV loading, filing deadlines, and similar cases."""

import csv
import re
from datetime import date
from decimal import Decimal

from django.conf import settings

from .models import CaseEntry, Claim, ClaimEvent, ClaimStatus, EventAction, PayerRule

# The answer key. Stored for scoring, never shown to a worker or sent to the AI.
ANSWER_KEY_FIELDS = [
    "expected_category",
    "expected_action",
    "expected_field",
    "expected_value",
    "expected_issue",
    "difficulty",
]

# Every column of sample_claims.csv, in file order.
CSV_COLUMNS = [
    "claim_id", "status",
    "patient_first", "patient_last", "patient_dob", "patient_sex",
    "payer_name", "payer_type", "member_id", "secondary_payer", "eligibility_note",
    "rendering_provider", "rendering_npi", "billing_npi", "place_of_service", "date_of_service",
    "icd10_primary", "icd10_secondary",
    "cpt_1", "modifiers_1", "units_1", "charge_1",
    "cpt_2", "modifiers_2", "units_2", "charge_2",
    "prior_auth_number", "referral_number", "ndc_code", "attachments", "clinical_note",
    "denial_code", "denial_reason",
    *ANSWER_KEY_FIELDS,
]  # fmt: skip

# The claim form, in the order and groups a worker sees.
FIELD_GROUPS = [
    ("Patient and Coverage", "user", [
        "patient_first", "patient_last", "patient_dob", "patient_sex",
        "payer_name", "member_id", "secondary_payer", "eligibility_note",
    ]),
    ("Provider", "users", ["rendering_provider", "place_of_service", "rendering_npi", "billing_npi"]),
    ("Service Lines", "list-checks", [
        "date_of_service",
        "cpt_1", "modifiers_1", "units_1", "charge_1",
        "cpt_2", "modifiers_2", "units_2", "charge_2",
    ]),
    ("Diagnoses", "file-text", ["icd10_primary", "icd10_secondary"]),
    ("Authorization and Documents", "library", ["prior_auth_number", "referral_number", "ndc_code", "attachments"]),
]  # fmt: skip
FORM_FIELDS = [name for _, _, fields in FIELD_GROUPS for name in fields]

DATE_COLUMNS = ["patient_dob", "date_of_service"]
INTEGER_COLUMNS = ["units_1", "units_2", "difficulty"]
DECIMAL_COLUMNS = ["charge_1", "charge_2"]


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def claim_from_row(row, assigned_to=None):
    """Build an unsaved Claim from one CSV row. Raises ValueError on a bad date or number."""
    values = {column: (row.get(column) or "").strip() for column in CSV_COLUMNS}
    for column in DATE_COLUMNS:
        values[column] = date.fromisoformat(values[column]) if values[column] else None
    for column in INTEGER_COLUMNS:
        values[column] = int(values[column]) if values[column] else None
    for column in DECIMAL_COLUMNS:
        values[column] = Decimal(values[column]) if values[column] else None
    values["status"] = values["status"] or ClaimStatus.NEW
    return Claim(**values, work_status=values["status"], assigned_to=assigned_to)


def filing_limits():
    """Each payer's filing limit in days, from its filing_limit rule."""
    rules = PayerRule.objects.filter(filing_limit_days__isnull=False)
    return {rule.payer_name: rule.filing_limit_days for rule in rules}


def days_left_to_file(claim, limits):
    """The payer's filing limit minus the days since the date of service, counted from DEMO_TODAY."""
    limit = limits.get(claim.payer_name)
    if limit is None:
        return None
    return limit - (settings.DEMO_TODAY - claim.date_of_service).days


def days_left_tone(days):
    """How to show days left: expired below zero, red under 15, amber under 30."""
    if days is None:
        return ""
    if days < 0:
        return "expired"
    if days < 15:
        return "red"
    if days < 30:
        return "amber"
    return ""


def similar_cases(claim, limit=3):
    """Case Library entries that match this claim, best match first.

    A case matches on the same CPT code, the same payer and diagnosis, or the same denial code.
    """
    cpts = {code.upper() for code in (claim.cpt_1, claim.cpt_2) if code}
    diagnoses = {code.upper() for code in (claim.icd10_primary, claim.icd10_secondary) if code}
    ranked = []
    for entry in CaseEntry.objects.select_related("created_by"):
        codes = set(re.split(r"[^A-Z0-9.]+", entry.codes.upper()))
        if codes & cpts:
            rank = 0
        elif entry.payer_name == claim.payer_name and codes & diagnoses:
            rank = 1
        elif claim.denial_code and entry.denial_code.upper() == claim.denial_code.upper():
            rank = 2
        else:
            continue
        ranked.append((rank, entry))
    # CaseEntry is ordered newest first, and sorting by rank keeps that order within a rank.
    ranked.sort(key=lambda pair: pair[0])
    return [entry for _, entry in ranked[:limit]]


def visible_claims():
    """Claims without the answer key loaded, for anything that reaches a template."""
    return Claim.objects.defer(*ANSWER_KEY_FIELDS)


def field_label(name):
    try:
        return str(Claim._meta.get_field(name).verbose_name)
    except Exception:
        return name


def save_claim_form(form, user):
    """Save a valid claim form and log one ClaimEvent per changed field. Returns the changed field names."""
    events = [
        ClaimEvent(
            claim=form.instance,
            user=user,
            action=EventAction.EDIT,
            field=name,
            old_value="" if form.initial.get(name) is None else str(form.initial.get(name)),
            new_value="" if form.cleaned_data[name] is None else str(form.cleaned_data[name]),
        )
        for name in form.changed_data
    ]
    if events:
        form.save()
        ClaimEvent.objects.bulk_create(events)
    return [event.field for event in events]


def claim_history(claim):
    """The claim's audit log, newest first, with a readable label for each changed field."""
    events = list(claim.events.select_related("user"))
    for event in events:
        event.label = field_label(event.field) if event.field else ""
    return events


def next_claim_id():
    """The next free claim ID, one above the highest CLM number in use."""
    numbers = [
        int(match.group(1))
        for claim_id in Claim.objects.values_list("claim_id", flat=True)
        if (match := re.fullmatch(r"CLM-(\d+)", claim_id))
    ]
    return f"CLM-{max(numbers, default=1000) + 1}"
