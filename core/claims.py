"""Helpers for working with claims: CSV loading for now, more as screens are added."""

import csv
from datetime import date
from decimal import Decimal

from .models import Claim, ClaimStatus

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
