from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from ..decorators import role_required
from ..models import HelpLevel, Role, TrainingAttempt, TrainingExercise
from ..skills import PLAIN_NAMES
from ..training import check, submit, todays_exercises, training_day


@role_required(Role.WORKER)
def training(request):
    """Today's ten practice cases and how the worker is doing on them."""
    exercises = todays_exercises(request.user)
    done = [exercise.attempt for exercise in exercises if exercise.attempt]
    correct = sum(attempt.correct for attempt in done)
    total = sum(attempt.total for attempt in done)
    context = {
        "exercises": exercises,
        "day": training_day(),
        "done_count": len(done),
        "percent": round(100 * len(done) / len(exercises)) if exercises else None,
        "next": next((exercise for exercise in exercises if not exercise.attempt), None),
        "tiles": [
            {"icon": "clipboard-check", "label": "Cases done today", "value": len(done)},
            {"icon": "target", "label": "Cases left", "value": len(exercises) - len(done)},
            {"icon": "circle-check", "label": "Sections correct", "value": correct},
            {"icon": "triangle-alert", "label": "Sections to review", "value": total - correct},
        ],
    }
    return render(request, "core/training.html", context)


@role_required(Role.WORKER)
def training_exercise(request, pk):
    """One practice case. Each section is checked, and wrong ones get feedback."""
    exercise = get_object_or_404(TrainingExercise, pk=pk)
    todays = todays_exercises(request.user)
    if exercise.pk not in [item.pk for item in todays]:
        raise Http404("This case is not in today's training.")
    attempt = TrainingAttempt.objects.filter(worker=request.user, exercise=exercise, day=training_day()).first()

    missing = []
    if request.method == "POST" and attempt is None:
        chosen = []
        for index, section in enumerate(exercise.sections):
            value = request.POST.get(f"section-{index}", "")
            chosen.append(int(value) if value.isdigit() and int(value) < len(section["options"]) else None)
        missing = [index for index, pick in enumerate(chosen) if pick is None]
        if not missing:
            attempt, improved = submit(request.user, exercise, chosen)
            for record in improved:
                name, level = PLAIN_NAMES[record.category][0], HelpLevel(record.help_level).label
                messages.add_message(
                    request, messages.SUCCESS, f"{name} improved. Help in this category is now {level}.", extra_tags="level"
                )
            return redirect("training_exercise", pk=exercise.pk)
        messages.error(request, "Answer every section before checking your work.")

    position = [item.pk for item in todays].index(exercise.pk)
    following = next((item for item in todays[position + 1 :] + todays[:position] if not item.attempt and item.pk != exercise.pk), None)
    context = {
        "exercise": exercise,
        "number": position + 1,
        "count": len(todays),
        "attempt": attempt,
        "results": check(exercise, attempt.answers) if attempt else None,
        "sections": list(enumerate(exercise.sections)),
        "missing": missing,
        "picked": {f"section-{i}": request.POST.get(f"section-{i}", "") for i in range(len(exercise.sections))},
        "following": following,
    }
    return render(request, "core/training_exercise.html", context)
