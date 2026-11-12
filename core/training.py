"""Daily training: ten practice cases a day, each checked section by section."""

import random

from django.conf import settings
from django.utils import timezone

from .models import Category, TrainingAttempt, TrainingExercise
from .skills import PLAIN_NAMES, record_training


def training_day():
    return timezone.localdate()


def todays_exercises(worker, day=None):
    """The worker's exercises for the day. The same ten all day, a new mix tomorrow."""
    day = day or training_day()
    exercises = list(TrainingExercise.objects.all())
    count = min(settings.RUNG_TRAINING_PER_DAY, len(exercises))
    picked = random.Random(f"{day.isoformat()}-{worker.pk}").sample(exercises, count)
    done = {a.exercise_id: a for a in TrainingAttempt.objects.filter(worker=worker, day=day)}
    for exercise in picked:
        exercise.attempt = done.get(exercise.pk)
    return picked


def check(exercise, chosen):
    """Check each section. chosen is the option index picked per section (None if skipped).

    Returns one result per section: whether it is correct, what was picked, and the feedback.
    """
    results = []
    for section, pick in zip(exercise.sections, chosen):
        correct = pick == section["answer"]
        results.append(
            {
                **section,
                "category_name": PLAIN_NAMES[Category(section["category"])][0],
                "picked": pick,
                "picked_text": section["options"][pick] if pick is not None else "No answer",
                "answer_text": section["options"][section["answer"]],
                "correct": correct,
            }
        )
    return results


def submit(worker, exercise, chosen, day=None):
    """Save the worker's answers and update the Skill Passport. Returns (attempt, improved records)."""
    results = check(exercise, chosen)
    attempt = TrainingAttempt.objects.create(
        worker=worker,
        exercise=exercise,
        day=day or training_day(),
        answers=chosen,
        correct=sum(r["correct"] for r in results),
        total=len(results),
    )
    improved = record_training(worker, [(r["category"], r["correct"]) for r in results])
    return attempt, improved
