"""Load the daily training exercises from data/training_exercises.json. Safe to run again."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import TrainingExercise


class Command(BaseCommand):
    help = "Load or update the training exercises. Does not touch claims or scores."

    def handle(self, *args, **options):
        exercises = json.loads((settings.BASE_DIR / "data" / "training_exercises.json").read_text())
        for item in exercises:
            code = item.pop("code")
            TrainingExercise.objects.update_or_create(code=code, defaults=item)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(exercises)} training exercises."))
