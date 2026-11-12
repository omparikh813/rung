from datetime import date
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from core.models import Category, HelpLevel, SkillRecord, TrainingAttempt, TrainingExercise
from core.skills import PLAIN_NAMES, passport, record_training
from core.tests.base import SeededTestCase
from core.training import check, todays_exercises


def right_answers(exercise):
    return {f"section-{i}": str(section["answer"]) for i, section in enumerate(exercise.sections)}


def wrong_answers(exercise):
    return {f"section-{i}": str((section["answer"] + 1) % len(section["options"])) for i, section in enumerate(exercise.sections)}


class ExerciseDataTests(SeededTestCase):
    def test_twenty_exercises_load_with_several_sections_each(self):
        self.assertEqual(TrainingExercise.objects.count(), 20)
        for exercise in TrainingExercise.objects.all():
            self.assertGreaterEqual(len(exercise.sections), 2, exercise.code)
            self.assertTrue(exercise.note and exercise.claim and exercise.rules, exercise.code)
            for section in exercise.sections:
                self.assertIn(section["category"], Category.values, exercise.code)
                self.assertLess(section["answer"], len(section["options"]), exercise.code)
                self.assertTrue(section["question"] and section["feedback"], exercise.code)

    def test_every_skill_area_is_practised(self):
        categories = {s["category"] for e in TrainingExercise.objects.all() for s in e.sections}
        self.assertEqual(categories, set(Category.values))

    def test_no_field_names_in_the_exercise_text(self):
        text = (settings.BASE_DIR / "data" / "training_exercises.json").read_text()
        for name in ("icd10_", "cpt_1", "modifiers_1", "ndc_code", "denial_code", "member_id", "date_of_service"):
            self.assertNotIn(name, text)

    def test_loader_is_safe_to_run_again(self):
        call_command("load_training", stdout=StringIO())
        self.assertEqual(TrainingExercise.objects.count(), 20)


class DailySetTests(SeededTestCase):
    def test_ten_exercises_a_day_the_same_all_day(self):
        first = [e.pk for e in todays_exercises(self.maria, date(2026, 11, 16))]
        self.assertEqual(len(first), 10)
        self.assertEqual(len(set(first)), 10)
        self.assertEqual(first, [e.pk for e in todays_exercises(self.maria, date(2026, 11, 16))])
        self.assertNotEqual(first, [e.pk for e in todays_exercises(self.maria, date(2026, 11, 17))])

    @override_settings(RUNG_TRAINING_PER_DAY=4)
    def test_number_per_day_is_a_setting(self):
        self.assertEqual(len(todays_exercises(self.maria)), 4)


class CheckingTests(SeededTestCase):
    def test_each_section_is_checked_on_its_own(self):
        exercise = TrainingExercise.objects.get(code="TR-02")
        picks = [exercise.sections[0]["answer"], 0, exercise.sections[2]["answer"]]
        results = check(exercise, picks)
        self.assertEqual([r["correct"] for r in results], [True, False, True])
        self.assertEqual(results[1]["picked_text"], "1 unit")
        self.assertEqual(results[1]["answer_text"], "3 units")
        self.assertIn("38 to 52 minutes is 3 units", results[1]["feedback"])


class TrainingPageTests(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.exercise = todays_exercises(self.maria)[0]
        self.url = reverse("training_exercise", args=[self.exercise.pk])

    def test_training_page_lists_todays_ten_cases(self):
        response = self.client.get(reverse("training"))
        self.assertEqual(len(response.context["exercises"]), 10)
        self.assertContains(response, "Ten practice cases a day")
        self.assertContains(response, "Not started", count=10)
        self.assertContains(response, self.url)

    def test_case_page_shows_note_claim_rules_and_every_section(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.exercise.note)
        for rule in self.exercise.rules:
            self.assertContains(response, rule)
        for section in self.exercise.sections:
            self.assertContains(response, section["question"])
        self.assertContains(response, "Check my work")
        # The answers are not given away before the worker answers.
        for section in self.exercise.sections:
            self.assertNotContains(response, section["feedback"])

    def test_all_right_marks_every_section_correct(self):
        response = self.client.post(self.url, right_answers(self.exercise), follow=True)
        self.assertRedirects(response, self.url)
        attempt = TrainingAttempt.objects.get()
        self.assertEqual((attempt.correct, attempt.total), (len(self.exercise.sections),) * 2)
        self.assertContains(response, "Correct", count=len(self.exercise.sections))
        self.assertNotContains(response, "Incorrect")

    def test_wrong_sections_are_flagged_with_feedback_and_the_right_answer(self):
        response = self.client.post(self.url, wrong_answers(self.exercise), follow=True)
        self.assertContains(response, "Incorrect", count=len(self.exercise.sections))
        for section in self.exercise.sections:
            self.assertContains(response, section["feedback"])
            self.assertContains(response, section["options"][section["answer"]])
        self.assertContains(response, "Correct answer:")
        self.assertEqual(TrainingAttempt.objects.get().correct, 0)

    def test_every_section_must_be_answered(self):
        data = right_answers(self.exercise)
        data.pop("section-0")
        response = self.client.post(self.url, data)
        self.assertContains(response, "Answer every section before checking your work.")
        self.assertContains(response, "Choose an answer for this section.", count=1)
        self.assertEqual(TrainingAttempt.objects.count(), 0)

    def test_one_try_per_case_per_day(self):
        self.client.post(self.url, wrong_answers(self.exercise))
        self.client.post(self.url, right_answers(self.exercise))
        self.assertEqual(TrainingAttempt.objects.count(), 1)
        self.assertEqual(TrainingAttempt.objects.get().correct, 0)

    def test_progress_shows_on_the_training_page(self):
        self.client.post(self.url, right_answers(self.exercise))
        response = self.client.get(reverse("training"))
        self.assertEqual(response.context["done_count"], 1)
        self.assertEqual(response.context["percent"], 10)
        self.assertContains(response, "Not started", count=9)

    def test_a_case_not_in_todays_set_cannot_be_opened(self):
        today = {e.pk for e in todays_exercises(self.maria)}
        other = TrainingExercise.objects.exclude(pk__in=today).first()
        self.assertEqual(self.client.get(reverse("training_exercise", args=[other.pk])).status_code, 404)

    def test_specialists_do_not_get_training(self):
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(reverse("training")).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_training_has_no_ai_and_no_specialist(self):
        response = self.client.get(self.url)
        for text in ("Ask a specialist", "AI review", "Re-check"):
            self.assertNotContains(response, text)


class TrainingScoringTests(SeededTestCase):
    def record(self, category=Category.MODIFIERS):
        return SkillRecord.objects.get(worker=self.maria, category=category)

    def test_five_correct_sections_equal_one_correct_real_claim(self):
        self.assertEqual(settings.RUNG_TRAINING_SECTIONS_PER_STEP, 5)
        record_training(self.maria, [(Category.MODIFIERS, True)] * 4)
        self.assertEqual((self.record().streak, self.record().training_progress), (0, 4))
        record_training(self.maria, [(Category.MODIFIERS, True)])
        self.assertEqual((self.record().streak, self.record().training_progress), (1, 0))
        self.assertEqual((self.record().training_correct, self.record().training_attempts), (5, 5))

    def test_training_moves_help_more_slowly_than_real_claims(self):
        improved = record_training(self.maria, [(Category.MODIFIERS, True)] * 14)
        self.assertEqual(improved, [])
        self.assertEqual(self.record().help_level, HelpLevel.FULL)
        improved = record_training(self.maria, [(Category.MODIFIERS, True)])
        self.assertEqual([r.category for r in improved], [Category.MODIFIERS])
        self.assertEqual(self.record().help_level, HelpLevel.GUIDED)

    def test_a_wrong_section_clears_training_progress_but_never_raises_help(self):
        SkillRecord.objects.create(worker=self.maria, category=Category.MODIFIERS, help_level=HelpLevel.GUIDED, streak=2)
        record_training(self.maria, [(Category.MODIFIERS, True), (Category.MODIFIERS, True), (Category.MODIFIERS, False)])
        record = self.record()
        self.assertEqual((record.help_level, record.streak, record.training_progress), (HelpLevel.GUIDED, 2, 0))

    def test_training_does_not_count_as_scored_claims(self):
        record_training(self.maria, [(Category.MODIFIERS, True)] * 3)
        data = passport(self.maria)
        self.assertContains(self.client.get(reverse("passport")), "five correct training sections")
        self.assertEqual(data["scored"], 0)
        modifiers = next(c for c in data["categories"] if c["key"] == "modifiers")
        self.assertEqual((modifiers["attempts"], modifiers["training_correct"]), (0, 3))

    def test_finishing_a_case_through_the_page_updates_the_passport_and_shows_a_toast(self):
        exercise = todays_exercises(self.maria)[0]
        category = exercise.sections[0]["category"]
        # One more correct section in this category completes a streak of three.
        SkillRecord.objects.create(worker=self.maria, category=category, streak=2, training_progress=4)
        response = self.client.post(reverse("training_exercise", args=[exercise.pk]), right_answers(exercise), follow=True)
        name = PLAIN_NAMES[Category(category)][0]
        self.assertContains(response, f"{name} improved. Help in this category is now Guided.")
        self.assertEqual(self.record(category).help_level, HelpLevel.GUIDED)
        self.assertContains(self.client.get(reverse("passport")), "Training")


class TrainingLayoutTests(SeededTestCase):
    def test_todays_cases_sit_in_two_columns(self):
        html = self.client.get(reverse("training")).content.decode()
        self.assertIn('class="mt-5 grid gap-5 sm:grid-cols-2"', html)
        self.assertNotIn("xl:grid-cols-3", html)


class TrainingHintTests(SeededTestCase):
    def setUp(self):
        super().setUp()
        self.exercise = todays_exercises(self.maria)[0]
        self.url = reverse("training_exercise", args=[self.exercise.pk])
        self.first = self.exercise.sections[0]

    def set_level(self, level):
        SkillRecord.objects.update_or_create(worker=self.maria, category=self.first["category"], defaults={"help_level": level})

    def test_every_section_has_both_hints(self):
        for exercise in TrainingExercise.objects.all():
            for section in exercise.sections:
                self.assertTrue(section["hint_full"].startswith("Rule: "), exercise.code)
                self.assertIn("Look at: ", section["hint_full"], exercise.code)
                self.assertTrue(section["hint_guided"].endswith("?"), exercise.code)

    def test_full_shows_the_rule_and_where_to_look(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.first["hint_full"])
        self.assertNotContains(response, self.first["hint_guided"])

    def test_guided_shows_one_question(self):
        self.set_level(HelpLevel.GUIDED)
        response = self.client.get(self.url)
        self.assertContains(response, self.first["hint_guided"])
        self.assertNotContains(response, self.first["hint_full"])

    def test_minimal_shows_no_hint(self):
        self.set_level(HelpLevel.MINIMAL)
        response = self.client.get(self.url)
        self.assertNotContains(response, self.first["hint_full"])
        self.assertNotContains(response, self.first["hint_guided"])
        self.assertContains(response, "No hint at Minimal.")

    def test_hints_follow_the_level_of_each_sections_own_skill_area(self):
        exercise = TrainingExercise.objects.get(code="TR-04")  # prior_auth then filing_rules
        SkillRecord.objects.create(worker=self.maria, category=Category.PRIOR_AUTH, help_level=HelpLevel.MINIMAL)
        from core.views.training import hinted_sections

        levels = [section["level"] for _, section in hinted_sections(self.maria, exercise)]
        self.assertEqual(levels, [HelpLevel.MINIMAL, HelpLevel.FULL, HelpLevel.MINIMAL])
