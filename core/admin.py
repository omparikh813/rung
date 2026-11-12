from django.contrib import admin

from .models import AIReview, Attempt, CaseEntry, Claim, ClaimEvent, HelpRequest, Organization, PayerRule, Profile, SkillRecord, TrainingAttempt, TrainingExercise


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "org_type", "seat_limit", "subscription_status", "renewal_date"]


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "organization"]
    list_filter = ["organization", "role"]


@admin.register(PayerRule)
class PayerRuleAdmin(admin.ModelAdmin):
    list_display = ["payer_name", "rule_type", "filing_limit_days", "source"]
    list_filter = ["payer_name", "rule_type"]


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ["claim_id", "patient_last", "payer_name", "date_of_service", "work_status", "assigned_to", "scored"]
    list_filter = ["work_status", "payer_name"]
    search_fields = ["claim_id", "patient_last"]


@admin.register(ClaimEvent)
class ClaimEventAdmin(admin.ModelAdmin):
    list_display = ["claim", "user", "action", "field", "created_at"]
    list_filter = ["action"]


@admin.register(AIReview)
class AIReviewAdmin(admin.ModelAdmin):
    list_display = ["claim", "model", "input_tokens", "output_tokens", "created_at"]


@admin.register(HelpRequest)
class HelpRequestAdmin(admin.ModelAdmin):
    list_display = ["claim", "worker", "specialist", "status", "outcome", "created_at"]
    list_filter = ["status"]


@admin.register(CaseEntry)
class CaseEntryAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "payer_name", "codes", "created_by", "created_at"]
    list_filter = ["category"]


@admin.register(SkillRecord)
class SkillRecordAdmin(admin.ModelAdmin):
    list_display = ["worker", "category", "help_level", "attempts", "correct", "streak", "escalations"]


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ["worker", "claim", "category", "action_taken", "correct", "assisted", "created_at"]


@admin.register(TrainingExercise)
class TrainingExerciseAdmin(admin.ModelAdmin):
    list_display = ["code", "title", "payer_name"]


@admin.register(TrainingAttempt)
class TrainingAttemptAdmin(admin.ModelAdmin):
    list_display = ["worker", "exercise", "day", "correct", "total"]
