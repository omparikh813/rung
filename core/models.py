from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    WORKER = "worker", "Worker"
    SPECIALIST = "specialist", "Specialist"


class ClaimStatus(models.TextChoices):
    """The status a claim arrives with."""

    NEW = "new", "New"
    DENIED = "denied", "Denied"


class WorkStatus(models.TextChoices):
    NEW = "new", "New"
    DENIED = "denied", "Denied"
    NEEDS_FIX = "needs_fix", "Needs Fix"
    READY = "ready", "Ready"
    WAITING = "waiting", "Waiting on Specialist"
    SUBMITTED = "submitted", "Submitted"
    PAID = "paid", "Paid"
    CLOSED = "closed", "Closed"


OPEN_STATUSES = [WorkStatus.NEW, WorkStatus.DENIED, WorkStatus.NEEDS_FIX, WorkStatus.READY]
DONE_STATUSES = [WorkStatus.SUBMITTED, WorkStatus.PAID, WorkStatus.CLOSED]


class Category(models.TextChoices):
    ELIGIBILITY = "eligibility", "Eligibility"
    PRIOR_AUTH = "prior_auth", "Prior authorization"
    CODE_MATCHING = "code_matching", "Code matching"
    MODIFIERS = "modifiers", "Modifiers"
    DOCUMENTATION = "documentation", "Documentation"
    FILING_RULES = "filing_rules", "Filing rules"


class HelpLevel(models.TextChoices):
    FULL = "full", "Full help"
    GUIDED = "guided", "Guided"
    MINIMAL = "minimal", "Minimal"


class EventAction(models.TextChoices):
    EDIT = "edit", "Changed a field"
    CHECK = "check", "AI review"
    ANSWER_SHOWN = "answer_shown", "Showed an answer"
    SUBMIT = "submit", "Submitted"
    PAYER = "payer", "Payer response"
    CLOSE = "close", "Closed"
    ESCALATE = "escalate", "Asked a specialist"
    RESOLVE = "resolve", "Specialist resolved"


class FinalAction(models.TextChoices):
    """The worker's final action on a claim, used for scoring."""

    SUBMIT = "submit", "Submitted"
    CLOSE = "close", "Closed"
    ESCALATE = "escalate", "Asked a specialist"


class RequestStatus(models.TextChoices):
    OPEN = "open", "Open"
    RESOLVED = "resolved", "Resolved"


class Outcome(models.TextChoices):
    RETURNED = "returned", "Fixed and returned to worker"
    SUBMITTED = "submitted", "Fixed and submitted"
    WRITE_OFF = "write_off", "Closed: write off"
    APPEAL = "appeal", "Closed: appeal sent"


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class PayerRule(models.Model):
    payer_name = models.CharField(max_length=100)
    rule_type = models.CharField(max_length=50)
    rule = models.TextField()
    filing_limit_days = models.PositiveIntegerField(null=True, blank=True)
    source = models.CharField(max_length=100)

    ALL_PAYERS = "All payers"

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.payer_name}: {self.rule_type}"


class Claim(models.Model):
    # Identity and status
    claim_id = models.CharField("Claim ID", max_length=30, unique=True)
    status = models.CharField("Status", max_length=10, choices=ClaimStatus.choices, default=ClaimStatus.NEW)

    # Patient and coverage
    patient_first = models.CharField("First name", max_length=60)
    patient_last = models.CharField("Last name", max_length=60)
    patient_dob = models.DateField("Date of birth", null=True, blank=True)
    patient_sex = models.CharField("Sex", max_length=1, blank=True)
    payer_name = models.CharField("Payer", max_length=100)
    payer_type = models.CharField("Payer type", max_length=30, blank=True)
    member_id = models.CharField("Member ID", max_length=30, blank=True)
    secondary_payer = models.CharField("Secondary payer", max_length=100, blank=True)
    eligibility_note = models.CharField("Eligibility note", max_length=200, blank=True)

    # Provider
    rendering_provider = models.CharField("Rendering provider", max_length=120, blank=True)
    rendering_npi = models.CharField("Rendering NPI", max_length=10, blank=True)
    billing_npi = models.CharField("Billing NPI", max_length=10, blank=True)
    place_of_service = models.CharField("Place of service", max_length=2, blank=True)
    date_of_service = models.DateField("Date of service")

    # Diagnoses
    icd10_primary = models.CharField("Primary ICD-10", max_length=10)
    icd10_secondary = models.CharField("Secondary ICD-10", max_length=10, blank=True)

    # Service lines
    cpt_1 = models.CharField("CPT (line 1)", max_length=10)
    modifiers_1 = models.CharField("Modifiers (line 1)", max_length=20, blank=True)
    units_1 = models.PositiveSmallIntegerField("Units (line 1)", null=True, blank=True)
    charge_1 = models.DecimalField("Charge (line 1)", max_digits=9, decimal_places=2, null=True, blank=True)
    cpt_2 = models.CharField("CPT (line 2)", max_length=10, blank=True)
    modifiers_2 = models.CharField("Modifiers (line 2)", max_length=20, blank=True)
    units_2 = models.PositiveSmallIntegerField("Units (line 2)", null=True, blank=True)
    charge_2 = models.DecimalField("Charge (line 2)", max_digits=9, decimal_places=2, null=True, blank=True)

    # Authorization and documents
    prior_auth_number = models.CharField("Prior auth number", max_length=30, blank=True)
    referral_number = models.CharField("Referral number", max_length=30, blank=True)
    ndc_code = models.CharField("NDC code", max_length=20, blank=True)
    attachments = models.CharField("Attachments", max_length=200, blank=True)
    clinical_note = models.TextField("Clinical note", blank=True)

    # Denial (denied claims only)
    denial_code = models.CharField("Denial code", max_length=20, blank=True)
    denial_reason = models.CharField("Denial reason", max_length=200, blank=True)

    # Answer key. Used only for scoring. Never shown to a worker or sent to the AI.
    expected_category = models.CharField(max_length=20, blank=True)
    expected_action = models.CharField(max_length=20, blank=True)
    expected_field = models.CharField(max_length=200, blank=True)
    expected_value = models.CharField(max_length=200, blank=True)
    expected_issue = models.TextField(blank=True)
    difficulty = models.PositiveSmallIntegerField(null=True, blank=True)

    # Work tracking
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="claims"
    )
    work_status = models.CharField(max_length=20, choices=WorkStatus.choices, default=WorkStatus.NEW)
    help_request_open = models.BooleanField(default=False)
    scored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.claim_id

    @property
    def is_open(self):
        return self.work_status in OPEN_STATUSES


class ClaimEvent(models.Model):
    """Audit log: one row per field change, check, submit, close, escalation, and resolution."""

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, choices=EventAction.choices)
    field = models.CharField(max_length=50, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.claim} {self.action}"


class AIReview(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="reviews")
    result_json = models.JSONField()
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    claim_version_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Review of {self.claim}"


class HelpRequest(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="help_requests")
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="help_requests")
    specialist = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="resolved_requests"
    )
    question = models.TextField()
    status = models.CharField(max_length=10, choices=RequestStatus.choices, default=RequestStatus.OPEN)
    outcome = models.CharField(max_length=20, choices=Outcome.choices, blank=True)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self):
        return f"Help request for {self.claim}"


class CaseEntry(models.Model):
    """A specialist fix saved for future workers. Never stores patient names, member IDs, or dates of birth."""

    title = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=Category.choices)
    payer_name = models.CharField("Payer", max_length=100, blank=True)
    codes = models.CharField(max_length=100, blank=True)
    denial_code = models.CharField(max_length=20, blank=True)
    problem = models.TextField()
    fix = models.TextField()
    tip = models.TextField(blank=True)
    source_request = models.ForeignKey(HelpRequest, null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "case entries"

    def __str__(self):
        return self.title


class SkillRecord(models.Model):
    """One row per worker per category, created on first use."""

    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skills")
    category = models.CharField(max_length=20, choices=Category.choices)
    help_level = models.CharField(max_length=10, choices=HelpLevel.choices, default=HelpLevel.FULL)
    attempts = models.PositiveIntegerField(default=0)
    correct = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    escalations = models.PositiveIntegerField(default=0)
    # Daily training counts for less than real claims: a few correct sections make one streak step.
    training_attempts = models.PositiveIntegerField(default=0)
    training_correct = models.PositiveIntegerField(default=0)
    training_progress = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["worker", "category"], name="one_skill_per_category")]

    def __str__(self):
        return f"{self.worker} {self.category}: {self.help_level}"


class Attempt(models.Model):
    """One row per scored claim. Feeds the Skill Passport history."""

    NO_CATEGORY = "none"

    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="attempts")
    category = models.CharField(max_length=20, choices=[*Category.choices, (NO_CATEGORY, "Clean claim")])
    action_taken = models.CharField(max_length=10, choices=FinalAction.choices)
    correct = models.BooleanField()
    assisted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.worker} {self.claim}: {'correct' if self.correct else 'incorrect'}"


class TrainingExercise(models.Model):
    """A practice case with fictional data. Each section is a question about one part of the claim."""

    code = models.CharField(max_length=10, unique=True)
    title = models.CharField(max_length=120)
    payer_name = models.CharField(max_length=100)
    note = models.TextField()
    claim = models.JSONField()  # label -> value, as shown to the worker
    rules = models.JSONField()  # the payer rules that apply
    sections = models.JSONField()  # category, title, question, options, answer, feedback

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} {self.title}"


class TrainingAttempt(models.Model):
    """One worker's answers to one exercise on one day."""

    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="training_attempts")
    exercise = models.ForeignKey(TrainingExercise, on_delete=models.CASCADE, related_name="attempts")
    day = models.DateField()
    answers = models.JSONField()  # the option the worker chose in each section
    correct = models.PositiveSmallIntegerField()
    total = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["worker", "exercise", "day"], name="one_try_per_exercise_per_day")]

    def __str__(self):
        return f"{self.worker} {self.exercise.code} {self.day}: {self.correct}/{self.total}"
