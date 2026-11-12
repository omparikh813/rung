from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from core.models import (
    Attempt,
    Category,
    Claim,
    ClaimEvent,
    EventAction,
    FinalAction,
    HelpLevel,
    Role,
    SkillRecord,
    WorkStatus,
)
from core.skills import is_correct, normalize, passport, score_claim
from core.tests.base import SeededTestCase, make_user

MODIFIER_FIXES = {"CLM-1012": "25", "CLM-1013": "GP", "CLM-1014": "QW", "CLM-1015": "95"}


class SkillsTestCase(SeededTestCase):
    def claim(self, claim_id):
        return Claim.objects.get(claim_id=claim_id)

    def edit(self, claim, **changes):
        """Change fields the way the workspace does, with an audit event per field."""
        for field, value in changes.items():
            ClaimEvent.objects.create(
                claim=claim, user=self.maria, action=EventAction.EDIT, field=field,
                old_value=str(getattr(claim, field) or ""), new_value=str(value),
            )  # fmt: skip
            setattr(claim, field, value)
        claim.save()
        return claim

    def fix_and_submit(self, claim_id, value=None):
        claim = self.edit(self.claim(claim_id), modifiers_1=value or MODIFIER_FIXES[claim_id])
        return score_claim(claim, self.maria, FinalAction.SUBMIT)

    def record(self, category=Category.MODIFIERS):
        return SkillRecord.objects.get(worker=self.maria, category=category)


class CorrectnessTests(SkillsTestCase):
    def test_normalize_ignores_case_spaces_and_dots(self):
        self.assertEqual(normalize(" s93.401a "), "S93401A")
        self.assertEqual(normalize("H25.11"), normalize("h2511"))
        self.assertEqual(normalize(2), "2")
        self.assertEqual(normalize(None), "")

    def test_clean_claim_is_correct_when_submitted_unchanged(self):
        claim = self.claim("CLM-1001")
        self.assertTrue(is_correct(claim, FinalAction.SUBMIT))
        self.assertFalse(is_correct(claim, FinalAction.CLOSE))
        self.assertFalse(is_correct(claim, FinalAction.ESCALATE))

    def test_clean_claim_is_incorrect_if_a_code_modifier_or_id_was_changed(self):
        for field, value in (("modifiers_1", "25"), ("icd10_primary", "I11.9"), ("member_id", "X1"), ("units_1", 2)):
            claim = self.edit(self.claim("CLM-1001"), **{field: value})
            self.assertFalse(is_correct(claim, FinalAction.SUBMIT), field)
            ClaimEvent.objects.all().delete()

    def test_clean_claim_stays_correct_if_only_other_fields_changed(self):
        claim = self.edit(self.claim("CLM-1001"), eligibility_note="Active, checked today")
        self.assertTrue(is_correct(claim, FinalAction.SUBMIT))

    def test_change_that_was_undone_does_not_count_as_a_change(self):
        claim = self.edit(self.claim("CLM-1001"), modifiers_1="25")
        claim = self.edit(claim, modifiers_1="")
        self.assertTrue(is_correct(claim, FinalAction.SUBMIT))

    def test_fix_needs_the_expected_value(self):
        claim = self.claim("CLM-1019")
        self.assertFalse(is_correct(claim, FinalAction.SUBMIT))
        self.assertTrue(is_correct(self.edit(claim, icd10_primary="s93401a"), FinalAction.SUBMIT))
        self.assertFalse(is_correct(self.edit(claim, icd10_primary="S93.401D"), FinalAction.SUBMIT))
        self.assertFalse(is_correct(self.edit(claim, icd10_primary="S93.401A"), FinalAction.ESCALATE))

    def test_fix_with_several_fields_needs_all_of_them(self):
        claim = self.edit(self.claim("CLM-1016"), modifiers_1="PT", icd10_primary="Z12.11")
        self.assertFalse(is_correct(claim, FinalAction.SUBMIT))
        self.assertTrue(is_correct(self.edit(claim, icd10_secondary="K63.5"), FinalAction.SUBMIT))
        other = self.edit(self.claim("CLM-1022"), payer_name="Crestline Insurance PPO", member_id="CRX20093357")
        self.assertTrue(is_correct(other, FinalAction.SUBMIT))

    def test_number_fix_compares_as_text(self):
        self.assertTrue(is_correct(self.edit(self.claim("CLM-1030"), units_1=2), FinalAction.SUBMIT))

    def test_escalate_and_close_claims(self):
        self.assertTrue(is_correct(self.claim("CLM-1021"), FinalAction.ESCALATE))
        self.assertFalse(is_correct(self.claim("CLM-1021"), FinalAction.SUBMIT))
        self.assertTrue(is_correct(self.claim("CLM-1029"), FinalAction.CLOSE))
        self.assertFalse(is_correct(self.claim("CLM-1029"), FinalAction.SUBMIT))


class HelpLevelTests(SkillsTestCase):
    def test_three_correct_modifier_claims_move_full_to_guided(self):
        self.assertIsNone(self.fix_and_submit("CLM-1012"))
        self.assertIsNone(self.fix_and_submit("CLM-1013"))
        self.assertEqual((self.record().help_level, self.record().streak), (HelpLevel.FULL, 2))
        improved = self.fix_and_submit("CLM-1014")
        self.assertEqual(improved, self.record())
        record = self.record()
        self.assertEqual(record.help_level, HelpLevel.GUIDED)
        self.assertEqual((record.attempts, record.correct, record.streak), (3, 3, 0))

    def test_an_incorrect_claim_moves_it_back_and_resets_the_streak(self):
        for claim_id in ("CLM-1012", "CLM-1013", "CLM-1014"):
            self.fix_and_submit(claim_id)
        self.assertEqual(self.record().help_level, HelpLevel.GUIDED)
        self.assertIsNone(self.fix_and_submit("CLM-1015", value="25"))
        record = self.record()
        self.assertEqual((record.help_level, record.streak), (HelpLevel.FULL, 0))
        self.assertEqual((record.attempts, record.correct), (4, 3))

    def test_incorrect_at_full_stays_at_full(self):
        self.fix_and_submit("CLM-1012", value="59")
        self.assertEqual((self.record().help_level, self.record().streak), (HelpLevel.FULL, 0))

    def test_assisted_answers_count_as_correct_but_do_not_add_to_the_streak(self):
        self.fix_and_submit("CLM-1012")
        self.fix_and_submit("CLM-1013")
        ClaimEvent.objects.create(claim=self.claim("CLM-1014"), user=self.maria, action=EventAction.ANSWER_SHOWN, new_value="0")
        self.assertIsNone(self.fix_and_submit("CLM-1014"))
        record = self.record()
        self.assertEqual((record.help_level, record.streak, record.correct), (HelpLevel.FULL, 2, 3))
        attempt = Attempt.objects.get(claim__claim_id="CLM-1014")
        self.assertTrue(attempt.correct and attempt.assisted)
        # The next unassisted correct claim completes the streak.
        self.assertIsNotNone(self.fix_and_submit("CLM-1015"))
        self.assertEqual(self.record().help_level, HelpLevel.GUIDED)

    def test_guided_moves_to_minimal_and_minimal_is_the_last_step(self):
        SkillRecord.objects.create(worker=self.maria, category=Category.MODIFIERS, help_level=HelpLevel.GUIDED, streak=2)
        self.assertIsNotNone(self.fix_and_submit("CLM-1012"))
        self.assertEqual(self.record().help_level, HelpLevel.MINIMAL)
        for claim_id in ("CLM-1013", "CLM-1014", "CLM-1015"):
            self.assertIsNone(self.fix_and_submit(claim_id))
        self.assertEqual(self.record().help_level, HelpLevel.MINIMAL)

    def test_streaks_are_per_category(self):
        self.fix_and_submit("CLM-1012")
        self.fix_and_submit("CLM-1013")
        score_claim(self.edit(self.claim("CLM-1019"), icd10_primary="S93.401A"), self.maria, FinalAction.SUBMIT)
        self.assertEqual(self.record().streak, 2)
        self.assertEqual(self.record(Category.CODE_MATCHING).streak, 1)

    def test_escalating_the_right_claim_is_correct_and_any_other_is_incorrect(self):
        score_claim(self.claim("CLM-1021"), self.maria, FinalAction.ESCALATE)
        record = self.record(Category.CODE_MATCHING)
        self.assertEqual((record.correct, record.escalations, record.streak), (1, 1, 1))
        score_claim(self.claim("CLM-1012"), self.maria, FinalAction.ESCALATE)
        record = self.record()
        self.assertEqual((record.correct, record.escalations, record.attempts), (0, 1, 1))

    @override_settings(RUNG_STREAK_TO_LOWER_HELP=2)
    def test_streak_length_is_a_setting(self):
        self.fix_and_submit("CLM-1012")
        self.assertIsNotNone(self.fix_and_submit("CLM-1013"))


class ScoreOnceTests(SkillsTestCase):
    def test_a_claim_is_scored_once(self):
        self.fix_and_submit("CLM-1012")
        self.assertTrue(self.claim("CLM-1012").scored)
        self.assertIsNone(score_claim(self.claim("CLM-1012"), self.maria, FinalAction.CLOSE))
        self.assertEqual(Attempt.objects.exclude(worker__username="cassandra").count(), 1)
        self.assertEqual(self.record().attempts, 1)

    def test_clean_claims_use_category_none_and_make_no_skill_record(self):
        score_claim(self.claim("CLM-1001"), self.maria, FinalAction.SUBMIT)
        attempt = Attempt.objects.exclude(worker__username="cassandra").get()
        self.assertEqual((attempt.category, attempt.correct), (Attempt.NO_CATEGORY, True))
        self.assertEqual(SkillRecord.objects.filter(worker=self.maria).count(), 0)

    def test_claims_without_an_answer_key_are_not_scored(self):
        claim = self.claim("CLM-1001")
        Claim.objects.filter(pk=claim.pk).update(expected_action="")
        self.assertIsNone(score_claim(claim, self.maria, FinalAction.SUBMIT))
        self.assertEqual(Attempt.objects.exclude(worker__username="cassandra").count(), 0)
        self.assertFalse(self.claim("CLM-1001").scored)

    def test_only_the_assigned_worker_is_scored(self):
        score_claim(self.claim("CLM-1001"), self.dan, FinalAction.SUBMIT)
        self.assertEqual(Attempt.objects.exclude(worker__username="cassandra").count(), 0)


class ScoringThroughTheWorkspaceTests(SkillsTestCase):
    def post(self, claim_id, **changes):
        claim = self.claim(claim_id)
        url = reverse("claim", args=[claim.pk])
        data = {k: "" if v is None else str(v) for k, v in self.client.get(url).context["form"].initial.items()}
        data.update(changes)
        return self.client.post(url, data, follow=True)

    def test_submit_scores_and_a_toast_names_the_improved_category(self):
        self.post("CLM-1012", modifiers_1="25", action="submit")
        response = self.post("CLM-1013", modifiers_1="GP", action="submit")
        self.assertNotContains(response, "improved")
        response = self.post("CLM-1014", modifiers_1="QW", action="submit")
        self.assertContains(response, "Modifiers improved. Help in this category is now Guided.")
        self.assertEqual(self.record().help_level, HelpLevel.GUIDED)
        self.assertEqual(Attempt.objects.filter(worker=self.maria, correct=True, action_taken=FinalAction.SUBMIT).count(), 3)

    def test_close_scores_the_duplicate_claim(self):
        self.post("CLM-1029", action="close", close_reason="duplicate")
        attempt = Attempt.objects.exclude(worker__username="cassandra").get()
        self.assertEqual((attempt.action_taken, attempt.correct, attempt.category), (FinalAction.CLOSE, True, Category.FILING_RULES))

    def test_show_answer_marks_the_attempt_assisted(self):
        claim = self.claim("CLM-1012")
        ClaimEvent.objects.create(claim=claim, user=self.maria, action=EventAction.ANSWER_SHOWN, new_value="0")
        self.post("CLM-1012", modifiers_1="25", action="submit")
        self.assertTrue(Attempt.objects.exclude(worker__username="cassandra").get().assisted)
        self.assertEqual(self.record().streak, 0)


class PassportTests(SkillsTestCase):
    def test_new_worker_starts_at_full_everywhere(self):
        data = passport(self.maria)
        self.assertEqual([c["level"] for c in data["categories"]], [HelpLevel.FULL] * 6)
        self.assertIsNone(data["accuracy"])
        self.assertFalse(data["ready"])
        self.assertEqual((data["completed"], data["scored"], data["escalations"]), (0, 0, 0))

    def test_stats_and_activity(self):
        self.fix_and_submit("CLM-1012")
        self.fix_and_submit("CLM-1013", value="59")
        ClaimEvent.objects.create(claim=self.claim("CLM-1014"), user=self.maria, action=EventAction.ANSWER_SHOWN, new_value="0")
        self.fix_and_submit("CLM-1014")
        score_claim(self.claim("CLM-1001"), self.maria, FinalAction.SUBMIT)
        Claim.objects.filter(claim_id__in=["CLM-1012", "CLM-1001"]).update(work_status=WorkStatus.SUBMITTED)
        data = passport(self.maria)
        self.assertEqual(data["scored"], 4)
        self.assertEqual(data["accuracy"], 75)
        self.assertEqual(data["completed"], 2)
        modifiers = next(c for c in data["categories"] if c["name"] == "Modifiers")
        self.assertEqual((modifiers["attempts"], modifiers["accuracy"]), (3, 67))
        results = {row["claim_id"]: row["result"] for row in data["activity"]}
        self.assertEqual(
            results,
            {"CLM-1012": "Correct", "CLM-1013": "Incorrect", "CLM-1014": "Correct with answer shown", "CLM-1001": "Correct"},
        )
        self.assertEqual(data["activity"][0]["category"], "Clean claim")

    def test_accuracy_uses_the_last_20_scored_claims(self):
        claims = list(Claim.objects.order_by("id")[:25])
        for index, claim in enumerate(claims):
            Attempt.objects.create(worker=self.maria, claim=claim, category=Attempt.NO_CATEGORY, action_taken=FinalAction.SUBMIT, correct=index >= 5)
        # The 5 oldest are incorrect and fall outside the last 20.
        self.assertEqual(passport(self.maria)["accuracy"], 100)

    def make_ready(self, scored=20, correct=17, minimal=4):
        claims = list(Claim.objects.order_by("id")[:scored])
        for index, claim in enumerate(claims):
            Attempt.objects.create(worker=self.maria, claim=claim, category=Attempt.NO_CATEGORY, action_taken=FinalAction.SUBMIT, correct=index < correct)
        for category in list(Category)[:minimal]:
            SkillRecord.objects.create(worker=self.maria, category=category, help_level=HelpLevel.MINIMAL)

    def test_ready_for_harder_claims_needs_all_three_thresholds(self):
        self.make_ready()
        self.assertTrue(passport(self.maria)["ready"])

    def test_not_ready_below_each_threshold(self):
        for kwargs in ({"scored": 19, "correct": 19}, {"correct": 16}, {"minimal": 3}):
            Attempt.objects.all().delete()
            SkillRecord.objects.all().delete()
            self.make_ready(**kwargs)
            self.assertFalse(passport(self.maria)["ready"], kwargs)

    def test_worker_sees_own_passport_page(self):
        self.fix_and_submit("CLM-1012")
        response = self.client.get(reverse("passport"))
        self.assertEqual(response.context["worker"], self.maria)
        for text in ("Skill Passport", "Claims completed", "Overall accuracy", "Escalations", "Ready for harder claims", "Recent activity", "How this works", "Approvals and referrals", "CLM-1012"):
            self.assertContains(response, text)
        self.assertNotContains(response, "worker-picker")

    def test_worker_cannot_see_another_workers_passport(self):
        make_user("other", Role.WORKER, self.ags)
        self.assertEqual(self.client.get(reverse("passport_user", args=["other"])).status_code, 403)
        self.assertEqual(self.client.get(reverse("passport_user", args=["flora"])).status_code, 200)

    def test_specialist_sees_any_worker_with_a_picker(self):
        make_user("other", Role.WORKER, self.ags)
        self.client.force_login(self.dan)
        self.assertRedirects(self.client.get(reverse("passport")), reverse("passport_user", args=["cassandra"]))
        response = self.client.get(reverse("passport_user", args=["other"]))
        self.assertEqual(response.context["worker"], get_user_model().objects.get(username="other"))
        self.assertContains(response, "worker-picker")
        self.assertContains(response, reverse("passport_user", args=["flora"]))
        self.assertEqual(self.client.get(reverse("passport_user", args=["james"])).status_code, 404)

    def test_passport_never_shows_the_answer_key(self):
        self.fix_and_submit("CLM-1012")
        response = self.client.get(reverse("passport"))
        self.assertNotContains(response, self.claim("CLM-1012").expected_issue)
        self.assertNotContains(response, "expected_")
