"""Claim Upload: read a CSV file and validate each row before anything is imported."""

import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .claims import ANSWER_KEY_FIELDS, CSV_COLUMNS, DATE_COLUMNS, DECIMAL_COLUMNS, INTEGER_COLUMNS, claim_from_row
from .models import Claim, ClaimStatus, PayerRule

REQUIRED_COLUMNS = ["claim_id", "patient_first", "patient_last", "payer_name", "date_of_service", "cpt_1", "icd10_primary"]
MAX_BYTES = 1_000_000
MAX_ROWS = 500
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def read_upload(upload):
    """Return (rows, error). Each row holds only the known columns. error is a message for the whole file."""
    if upload is None:
        return [], "Choose a CSV file first."
    if upload.size > MAX_BYTES:
        return [], "That file is too large. The limit is 1 MB."
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], "That file could not be read. Save it as a CSV file and try again."
    reader = csv.DictReader(io.StringIO(text))
    columns = [name.strip() for name in reader.fieldnames or []]
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        return [], f"The file is missing required columns: {', '.join(missing)}."
    rows = []
    for raw in reader:
        row = {(key or "").strip(): (value or "").strip() for key, value in raw.items() if isinstance(value, str)}
        if any(row.values()):
            rows.append({name: row.get(name, "") for name in CSV_COLUMNS})
    if not rows:
        return [], "The file has no claim rows."
    if len(rows) > MAX_ROWS:
        return [], f"The file has more than {MAX_ROWS} rows. Split it into smaller files."
    return rows, ""


def row_errors(row, known_payers, taken_ids):
    """Every problem with one row, in plain words."""
    errors = [f"{name} is missing" for name in REQUIRED_COLUMNS if not row[name]]
    if row["claim_id"] and row["claim_id"] in taken_ids:
        errors.append(f"claim ID {row['claim_id']} already exists")
    if row["payer_name"] and row["payer_name"] not in known_payers:
        errors.append(f"payer {row['payer_name']} is not in the payer rules")
    for name in DATE_COLUMNS:
        if row[name]:
            try:
                valid = bool(ISO_DATE.match(row[name])) and date.fromisoformat(row[name])
            except ValueError:
                valid = False
            if not valid:
                errors.append(f"{name} must be a real date written as YYYY-MM-DD")
    if row["status"] and row["status"] not in ClaimStatus.values:
        errors.append("status must be new or denied")
    for name in INTEGER_COLUMNS:
        if row[name] and not row[name].isdigit():
            errors.append(f"{name} must be a whole number")
    for name in DECIMAL_COLUMNS:
        if row[name]:
            try:
                if not Decimal(row[name]).is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                errors.append(f"{name} must be an amount such as 150.00")
    if not errors:
        # A last check against the model catches anything else, such as text that is too long.
        try:
            claim_from_row(row).full_clean(exclude=["assigned_to"], validate_unique=False)
        except ValidationError as error:
            errors.extend(f"{name}: {' '.join(messages)}" for name, messages in error.message_dict.items())
    return errors


def check_rows(rows):
    """Validate every row. Returns a list of {number, row, errors} in file order."""
    known_payers = set(PayerRule.objects.exclude(payer_name=PayerRule.ALL_PAYERS).values_list("payer_name", flat=True))
    taken_ids = set(Claim.objects.values_list("claim_id", flat=True))
    checked = []
    for number, row in enumerate(rows, start=1):
        errors = row_errors(row, known_payers, taken_ids)
        checked.append({"number": number, "row": row, "errors": errors})
        if row["claim_id"]:
            taken_ids.add(row["claim_id"])  # A later row with the same ID is a duplicate.
    return checked


def import_rows(rows, user):
    """Import only the valid rows, assigned to the uploader. Returns (imported, skipped)."""
    checked = check_rows(rows)
    valid = [item["row"] for item in checked if not item["errors"]]
    for row in valid:
        claim_from_row(row, assigned_to=user).save()
    return len(valid), len(checked) - len(valid)


def has_answer_key(row):
    return any(row.get(name) for name in ANSWER_KEY_FIELDS)
