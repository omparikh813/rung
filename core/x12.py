"""Build an ANSI X12 837P (professional claim, version 005010X222A1) file for one claim.

The demo does not hold everything a real 837P needs, such as the billing provider's
address and tax ID. Those come from the placeholders in settings.RUNG_X12.
"""

import re

from django.conf import settings
from django.utils import timezone

ELEMENT = "*"
COMPONENT = ":"
REPETITION = "^"
TERMINATOR = "~"
VERSION = "005010X222A1"

# How the payer type maps to the X12 claim filing indicator.
FILING_CODES = {"medicare": "MB", "medicaid": "MC"}
DEFAULT_FILING_CODE = "CI"  # Commercial insurance


def clean(value):
    """Uppercase text with the X12 delimiter characters removed."""
    text = "" if value is None else str(value)
    return re.sub(r"[*:^~\r\n]", " ", text).strip().upper()


def segment(*elements):
    """One segment. Empty elements at the end are dropped."""
    parts = [clean(element) if not isinstance(element, Raw) else element for element in elements]
    while parts and parts[-1] == "":
        parts.pop()
    return ELEMENT.join(parts) + TERMINATOR


class Raw(str):
    """An element that is already formatted, such as a composite with colons."""


def composite(*parts):
    parts = [clean(part) for part in parts]
    while parts and parts[-1] == "":
        parts.pop()
    return Raw(COMPONENT.join(parts))


def provider_name(text):
    """Split "Dr. Lena Ortiz (Family Medicine)" into (last, first)."""
    name = re.sub(r"\(.*?\)", "", text or "")
    name = re.sub(r"^\s*(dr\.?|doctor)\s+", "", name, flags=re.IGNORECASE).strip()
    if not name:
        return "", ""
    first, _, last = name.rpartition(" ")
    return (last, first) if first else (name, "")


def amount(value):
    return f"{value:.2f}".rstrip("0").rstrip(".") if value is not None else "0"


def service_lines(claim):
    lines = [(claim.cpt_1, claim.modifiers_1, claim.units_1, claim.charge_1)]
    if claim.cpt_2:
        lines.append((claim.cpt_2, claim.modifiers_2, claim.units_2, claim.charge_2))
    return lines


def build_837p(claim, when=None):
    """The claim as the text of an 837P interchange with one claim in it."""
    config = settings.RUNG_X12
    when = when or timezone.now()
    control = f"{claim.pk:09d}"
    lines = service_lines(claim)
    total = sum(charge or 0 for _, _, _, charge in lines)
    diagnoses = [code.replace(".", "") for code in (claim.icd10_primary, claim.icd10_secondary) if code]
    filing_code = FILING_CODES.get(claim.payer_type.lower(), DEFAULT_FILING_CODE)
    rendering_last, rendering_first = provider_name(claim.rendering_provider)

    # The ISA header is fixed width, so it is written by hand.
    isa = ELEMENT.join(
        [
            "ISA", "00", " " * 10, "00", " " * 10,
            "ZZ", clean(config["sender_id"])[:15].ljust(15),
            "ZZ", clean(config["receiver_id"])[:15].ljust(15),
            when.strftime("%y%m%d"), when.strftime("%H%M"),
            REPETITION, "00501", control, "0", config["usage_indicator"], COMPONENT,
        ]
    ) + TERMINATOR  # fmt: skip

    body = [
        segment("ST", "837", "0001", VERSION),
        segment("BHT", "0019", "00", claim.claim_id, when.strftime("%Y%m%d"), when.strftime("%H%M"), "CH"),
        # Loop 1000A: submitter. Loop 1000B: receiver.
        segment("NM1", "41", "2", config["submitter_name"], "", "", "", "", "46", config["sender_id"]),
        segment("PER", "IC", config["submitter_contact"], "TE", config["submitter_phone"]),
        segment("NM1", "40", "2", config["receiver_name"], "", "", "", "", "46", config["receiver_id"]),
        # Loop 2000A and 2010AA: billing provider.
        segment("HL", "1", "", "20", "1"),
        segment("NM1", "85", "2", config["billing_provider_name"], "", "", "", "", "XX", claim.billing_npi),
        segment("N3", config["billing_provider_address"]),
        segment("N4", config["billing_provider_city"], config["billing_provider_state"], config["billing_provider_zip"]),
        segment("REF", "EI", config["billing_provider_tax_id"]),
        # Loop 2000B and 2010BA: the subscriber is the patient.
        segment("HL", "2", "1", "22", "0"),
        segment("SBR", "P", "18", "", "", "", "", "", "", filing_code),
        segment("NM1", "IL", "1", claim.patient_last, claim.patient_first, "", "", "", "MI", claim.member_id),
        segment("N3", config["subscriber_address"]),
        segment("N4", config["subscriber_city"], config["subscriber_state"], config["subscriber_zip"]),
    ]
    if claim.patient_dob:
        sex = claim.patient_sex if claim.patient_sex in ("M", "F") else "U"
        body.append(segment("DMG", "D8", claim.patient_dob.strftime("%Y%m%d"), sex))
    body += [
        # Loop 2010BB: payer.
        segment("NM1", "PR", "2", claim.payer_name, "", "", "", "", "PI", config["payer_id"]),
        # Loop 2300: the claim.
        segment("CLM", claim.claim_id, amount(total), "", "", composite(claim.place_of_service, "B", "1"), "Y", "A", "Y", "Y"),
    ]
    if claim.referral_number:
        body.append(segment("REF", "9F", claim.referral_number))
    if claim.prior_auth_number:
        body.append(segment("REF", "G1", claim.prior_auth_number))
    qualifiers = ["ABK", *["ABF"] * (len(diagnoses) - 1)]
    body.append(segment("HI", *[composite(qualifier, code) for qualifier, code in zip(qualifiers, diagnoses)]))
    if rendering_last:
        # Loop 2310B: rendering provider.
        body.append(segment("NM1", "82", "1", rendering_last, rendering_first, "", "", "", "XX", claim.rendering_npi))
    for number, (cpt, modifiers, units, charge) in enumerate(lines, start=1):
        # Loop 2400: one service line.
        codes = re.findall(r"[A-Za-z0-9]{2}", modifiers or "")[:4]
        pointers = composite(*[str(i) for i in range(1, len(diagnoses) + 1)])
        body.append(segment("LX", str(number)))
        body.append(segment("SV1", composite("HC", cpt, *codes), amount(charge), "UN", str(units or 1), "", "", pointers))
        body.append(segment("DTP", "472", "D8", claim.date_of_service.strftime("%Y%m%d")))
        if number == 1 and claim.ndc_code:
            body.append(segment("LIN", "", "N4", claim.ndc_code))
    body.append(segment("SE", str(len(body) + 1), "0001"))

    envelope = [
        isa,
        segment("GS", "HC", config["sender_id"], config["receiver_id"], when.strftime("%Y%m%d"), when.strftime("%H%M"), "1", "X", VERSION),
        *body,
        segment("GE", "1", "1"),
        segment("IEA", "1", control),
    ]
    return "\n".join(envelope) + "\n"
