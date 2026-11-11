"""Prompt assembly and the OpenRouter client. RUNG makes one kind of AI request: a claim review."""

import hashlib
import json
import logging
import os
from pathlib import Path

import httpx
from django.conf import settings

from .claims import ANSWER_KEY_FIELDS, CSV_COLUMNS, similar_cases
from .models import AIReview, Category, Claim, PayerRule

logger = logging.getLogger(__name__)

URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPTS = Path(settings.BASE_DIR) / "prompts"

# The claim fields a worker can see. The answer key is never sent to the AI.
CLAIM_BLOCK_FIELDS = [name for name in CSV_COLUMNS if name not in (*ANSWER_KEY_FIELDS, "clinical_note")]


class AIError(Exception):
    """The AI review could not be completed. The app shows a Try again message."""


def ask(task: str, blocks: dict) -> tuple[dict, dict]:
    """Send one AI request. Returns the parsed JSON reply and the token usage."""
    context = "\n".join(f"<{k}>\n{v}\n</{k}>" for k, v in blocks.items())
    master = (PROMPTS / "master.md").read_text()
    task_text = (PROMPTS / f"{task}.md").read_text()
    messages = [
        {"role": "system", "content": master},
        {"role": "user", "content": f"{context}\n<task>\n{task_text}\n</task>"},
    ]
    headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"}
    for attempt in range(2):
        payload = {"model": settings.RUNG_MODEL, "temperature": 0, "messages": messages}
        r = httpx.post(URL, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        body = r.json()
        text = body["choices"][0]["message"]["content"].strip()
        text = text.strip("`").removeprefix("json").strip()
        try:
            return json.loads(text), body.get("usage", {})
        except json.JSONDecodeError:
            messages.append({"role": "user", "content": "Return valid JSON only."})
    raise ValueError("AI returned invalid JSON")


def claim_block(claim):
    """The worker visible claim fields as a dict of strings."""
    block = {}
    for name in CLAIM_BLOCK_FIELDS:
        value = getattr(claim, name)
        block[name] = "" if value is None else str(value)
    return block


def claim_version_hash(claim):
    """Changes whenever a field the AI sees changes, so an unchanged claim reuses its review."""
    content = json.dumps({**claim_block(claim), "clinical_note": claim.clinical_note}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def payer_rules_block(claim):
    rules = PayerRule.objects.filter(payer_name__in=[claim.payer_name, PayerRule.ALL_PAYERS])
    lines = []
    for rule in rules:
        limit = f" Filing limit: {rule.filing_limit_days} days." if rule.filing_limit_days else ""
        lines.append(f"- [{rule.payer_name}, {rule.rule_type}] {rule.rule}{limit} (source: {rule.source})")
    return "\n".join(lines) or "none"


def patient_claims_block(claim):
    """The same patient's claims created before this one, so only the later claim is the duplicate."""
    earlier = Claim.objects.filter(
        patient_first=claim.patient_first,
        patient_last=claim.patient_last,
        patient_dob=claim.patient_dob,
        pk__lt=claim.pk,
    )
    rows = [
        {
            "claim_id": other.claim_id,
            "date_of_service": str(other.date_of_service),
            "cpt_codes": [code for code in (other.cpt_1, other.cpt_2) if code],
            "status": other.get_work_status_display(),
        }
        for other in earlier
    ]
    return json.dumps(rows, indent=2) if rows else "none"


def similar_cases_block(claim):
    rows = [
        {"title": entry.title, "problem": entry.problem, "fix": entry.fix, "tip": entry.tip}
        for entry in similar_cases(claim)
    ]
    return json.dumps(rows, indent=2) if rows else "none"


def build_blocks(claim):
    """The context blocks for a claim review, in the order the task prompt lists them."""
    return {
        "today": settings.DEMO_TODAY.isoformat(),
        "claim": json.dumps(claim_block(claim), indent=2),
        "clinical_note": claim.clinical_note or "none",
        "payer_rules": payer_rules_block(claim),
        "patient_claims": patient_claims_block(claim),
        "similar_cases": similar_cases_block(claim),
    }


def clean_review(data):
    """Check the AI reply has the shape the app needs and fill safe defaults."""
    if not isinstance(data, dict) or not isinstance(data.get("issues"), list):
        raise ValueError("AI review has the wrong shape")
    issues = []
    for raw in data["issues"]:
        if not isinstance(raw, dict):
            raise ValueError("AI review has the wrong shape")
        category = raw.get("category") if raw.get("category") in Category.values else ""
        field = str(raw.get("field") or "")
        # Guided and minimal text must never fall back to text that reveals the fix.
        minimal = str(raw.get("minimal") or f"{Category(category).label if category else 'Claim'}: {field}")
        suggested = raw.get("suggested_value")
        issues.append(
            {
                "category": category,
                "field": field,
                "full": str(raw.get("full") or raw.get("answer") or minimal),
                "guided": str(raw.get("guided") or minimal),
                "minimal": minimal,
                "answer": str(raw.get("answer") or raw.get("full") or ""),
                "suggested_value": None if suggested is None else str(suggested),
                "confidence": "high" if raw.get("confidence") == "high" else "low",
                "escalate": bool(raw.get("escalate")),
            }
        )
    escalate = bool(data.get("escalate")) or any(issue["escalate"] for issue in issues)
    return {
        "summary": str(data.get("summary") or ""),
        "ready_to_submit": not issues,
        "issues": issues,
        "escalate": escalate,
        "escalate_reason": str(data["escalate_reason"]) if data.get("escalate_reason") else None,
    }


def latest_review(claim):
    return claim.reviews.first()


def review_claim(claim):
    """Return the claim's review, reusing the latest one if the claim has not changed."""
    version = claim_version_hash(claim)
    latest = latest_review(claim)
    if latest and latest.claim_version_hash == version:
        return latest
    try:
        result, usage = ask("review_claim", build_blocks(claim))
        result = clean_review(result)
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        # Log the kind of failure only. The request headers hold the API key.
        logger.warning("AI review failed for %s: %s", claim.claim_id, type(error).__name__)
        raise AIError("The AI review could not be completed.") from error
    return AIReview.objects.create(
        claim=claim,
        result_json=result,
        model=settings.RUNG_MODEL,
        input_tokens=usage.get("prompt_tokens") or 0,
        output_tokens=usage.get("completion_tokens") or 0,
        claim_version_hash=version,
    )
