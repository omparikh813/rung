"""Skill tracking and fading help: scoring claims, help levels, and the Skill Passport."""

import re

from django.conf import settings
from django.db import transaction

from .models import (
    DONE_STATUSES,
    Attempt,
    Category,
    Claim,
    EventAction,
    FinalAction,
    HelpLevel,
    HelpRequest,
    SkillRecord,
)

# Help fades in this order as the worker improves.
LEVELS = [HelpLevel.FULL, HelpLevel.GUIDED, HelpLevel.MINIMAL]

# A clean claim is correct only if none of these were changed before it was submitted.
PROTECTED_FIELDS = [
    "cpt_1", "modifiers_1", "units_1", "charge_1", "cpt_2", "modifiers_2", "units_2", "charge_2",
    "icd10_primary", "icd10_secondary",
    "member_id", "rendering_npi", "billing_npi", "prior_auth_number", "referral_number", "ndc_code",
]  # fmt: skip

# Category names in plain words for the Skill Passport.
PLAIN_NAMES = {
    Category.ELIGIBILITY: ("Coverage and eligibility", "Is the patient covered, and is the right plan billed first?"),
    Category.PRIOR_AUTH: ("Approvals and referrals", "Does the claim carry the approval or referral number the payer asks for?"),
    Category.CODE_MATCHING: ("Matching codes to the note", "Do the diagnosis and procedure codes say what the note says?"),
    Category.MODIFIERS: ("Modifiers", "Are the two character add ons to the procedure code right?"),
    Category.DOCUMENTATION: ("Documentation", "Does the claim have the records and numbers the payer needs?"),
    Category.FILING_RULES: ("Filing rules", "Deadlines, duplicates, and unit counts."),
}  # fmt: skip


def help_levels(worker):
    """The worker's help level in each category they have a record for. Missing means FULL."""
    return dict(SkillRecord.objects.filter(worker=worker).values_list("category", "help_level"))


def help_level(levels, category):
    return levels.get(category, HelpLevel.FULL)


def normalize(value):
    """Compare values in uppercase with spaces and dots removed."""
    return re.sub(r"[\s.]", "", "" if value is None else str(value)).upper()


def original_value(claim, field):
    """The field's value before anyone edited it: the old value of its first edit."""
    first_edit = claim.events.filter(action=EventAction.EDIT, field=field).order_by("created_at", "id").first()
    return first_edit.old_value if first_edit else getattr(claim, field)


def is_correct(claim, action):
    """Whether the worker's final action matches the answer key."""
    expected = claim.expected_action
    if expected == "submit":
        unchanged = all(normalize(getattr(claim, f)) == normalize(original_value(claim, f)) for f in PROTECTED_FIELDS)
        return action == FinalAction.SUBMIT and unchanged
    if expected == "fix":
        fields = claim.expected_field.split(";")
        values = claim.expected_value.split(";")
        fixed = all(normalize(getattr(claim, f.strip(), None)) == normalize(v) for f, v in zip(fields, values))
        return action == FinalAction.SUBMIT and len(fields) == len(values) and fixed
    if expected == "escalate":
        return action == FinalAction.ESCALATE
    if expected == "close":
        return action == FinalAction.CLOSE
    return False


def add_streak_step(record):
    """Add one step to the streak. Returns True if that lowered the help level."""
    step = LEVELS.index(record.help_level)
    record.streak += 1
    if record.streak >= settings.RUNG_STREAK_TO_LOWER_HELP and step < len(LEVELS) - 1:
        record.help_level = LEVELS[step + 1]
        record.streak = 0
        return True
    return False


@transaction.atomic
def record_training(worker, results):
    """Update the Skill Passport from one training exercise.

    results is a list of (category, correct) pairs, one per section. Training counts
    for less than real work: it takes RUNG_TRAINING_SECTIONS_PER_STEP correct sections
    in a category to equal one correct real claim. A wrong section clears that
    progress but never raises the help level. Returns the records whose level dropped.
    """
    improved = []
    for category, correct in results:
        if category not in Category.values:
            continue
        record, _ = SkillRecord.objects.get_or_create(worker=worker, category=category)
        record.training_attempts += 1
        if correct:
            record.training_correct += 1
            record.training_progress += 1
            if record.training_progress >= settings.RUNG_TRAINING_SECTIONS_PER_STEP:
                record.training_progress = 0
                if add_streak_step(record):
                    improved.append(record)
        else:
            record.training_progress = 0
        record.save()
    return improved


@transaction.atomic
def score_claim(claim, worker, action):
    """Score the worker's first final action on a claim that has an answer key.

    Returns the SkillRecord if this claim lowered the worker's help level, otherwise None.
    """
    claim = Claim.objects.select_for_update().get(pk=claim.pk)
    if claim.scored or not claim.expected_action or claim.assigned_to_id != worker.pk:
        return None

    correct = is_correct(claim, action)
    assisted = claim.events.filter(action=EventAction.ANSWER_SHOWN).exists()
    category = claim.expected_category if claim.expected_category in Category.values else Attempt.NO_CATEGORY
    Attempt.objects.create(
        worker=worker, claim=claim, category=category, action_taken=action, correct=correct, assisted=assisted
    )
    Claim.objects.filter(pk=claim.pk).update(scored=True)
    if category == Attempt.NO_CATEGORY:
        return None  # Clean claims count toward overall accuracy only.

    record, _ = SkillRecord.objects.get_or_create(worker=worker, category=category)
    step = LEVELS.index(record.help_level)
    improved = False
    record.attempts += 1
    if action == FinalAction.ESCALATE:
        record.escalations += 1
    if correct:
        record.correct += 1
        if not assisted:  # Assisted answers count for accuracy but do not add to the streak.
            improved = add_streak_step(record)
    else:
        record.help_level = LEVELS[max(step - 1, 0)]
        record.streak = 0
    record.save()
    return record if improved else None


def passport(worker):
    """Everything the Skill Passport shows for one worker. Holds no answer key data."""
    attempts = list(
        Attempt.objects.filter(worker=worker).values(
            "claim_id", "claim__claim_id", "category", "action_taken", "correct", "assisted", "created_at"
        )
    )
    recent = attempts[:20]
    accuracy = round(100 * sum(a["correct"] for a in recent) / len(recent)) if recent else None

    records = {record.category: record for record in SkillRecord.objects.filter(worker=worker)}
    categories = []
    for category in Category:
        record = records.get(category)
        name, about = PLAIN_NAMES[category]
        categories.append(
            {
                "key": category.value,
                "name": name,
                "about": about,
                "level": record.help_level if record else HelpLevel.FULL,
                "level_label": HelpLevel(record.help_level if record else HelpLevel.FULL).label,
                "attempts": record.attempts if record else 0,
                "accuracy": round(100 * record.correct / record.attempts) if record and record.attempts else None,
                "streak": record.streak if record else 0,
                "training_correct": record.training_correct if record else 0,
                "training_attempts": record.training_attempts if record else 0,
            }
        )
    minimal = sum(c["level"] == HelpLevel.MINIMAL for c in categories)

    category_names = {c.value: PLAIN_NAMES[c][0] for c in Category} | {Attempt.NO_CATEGORY: "Clean claim"}
    activity = [
        {
            "claim_pk": a["claim_id"],
            "claim_id": a["claim__claim_id"],
            # A claim the worker submitted can be exported as an 837P file.
            "exportable": a["action_taken"] == FinalAction.SUBMIT,
            "category": category_names[a["category"]],
            "action": FinalAction(a["action_taken"]).label,
            "result": "Incorrect" if not a["correct"] else "Correct with answer shown" if a["assisted"] else "Correct",
            "correct": a["correct"],
            "date": a["created_at"],
        }
        for a in recent
    ]
    goals = [
        {"label": f"{settings.RUNG_READY_MIN_SCORED} scored claims", "now": f"{len(attempts)} so far",
         "met": len(attempts) >= settings.RUNG_READY_MIN_SCORED},
        {"label": f"{settings.RUNG_READY_MIN_ACCURACY}% accuracy over the last 20",
         "now": f"{accuracy}% now" if accuracy is not None else "no scored claims yet",
         "met": accuracy is not None and accuracy >= settings.RUNG_READY_MIN_ACCURACY},
        {"label": f"{settings.RUNG_READY_MIN_MINIMAL} categories at Minimal help", "now": f"{minimal} so far",
         "met": minimal >= settings.RUNG_READY_MIN_MINIMAL},
    ]  # fmt: skip
    completed = Claim.objects.filter(assigned_to=worker, work_status__in=DONE_STATUSES).count()
    escalations = HelpRequest.objects.filter(worker=worker).count()
    return {
        "tiles": [
            {"icon": "circle-check", "label": "Claims completed", "value": completed},
            {"icon": "target", "label": "Claims scored", "value": len(attempts)},
            {"icon": "life-buoy", "label": "Escalations", "value": escalations},
            {"icon": "award", "label": "Areas at Minimal help", "value": minimal},
        ],
        "completed": completed,
        "scored": len(attempts),
        "accuracy": accuracy,
        "escalations": escalations,
        "categories": categories,
        "activity": activity,
        "goals": goals,
        "ready": all(goal["met"] for goal in goals),
        "streak_goal": range(settings.RUNG_STREAK_TO_LOWER_HELP),
    }
