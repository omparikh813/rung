"""Reset the demo: delete demo data, then load the organizations, their people, claims, and rules."""

import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.claims import claim_from_row, read_csv
from core.models import (
    AIReview,
    Attempt,
    CaseEntry,
    Category,
    Claim,
    ClaimEvent,
    ContractTerm,
    FinalAction,
    HelpLevel,
    HelpRequest,
    Organization,
    OrganizationType,
    PayerRule,
    Profile,
    Role,
    SkillRecord,
    SubscriptionStatus,
    Ticket,
    TicketMessage,
    TrainingAttempt,
    WorkStatus,
)
from core.organizations import FEATURES

ORGANIZATIONS = [
    {
        "name": "AGS Health",
        "org_type": OrganizationType.RCM,
        "directory_company": "AGS Health",
        "seat_limit": 10,
        "contract_term": ContractTerm.ANNUAL,
        "subscription_status": SubscriptionStatus.ACTIVE,
        "contract_start": date(2026, 7, 1),
        "renewal_date": date(2027, 6, 30),
        "features": list(FEATURES),
        "claim_prefix": "CLM",
    },
    {
        "name": "Summit Medical Billing",
        "org_type": OrganizationType.BILLING,
        "directory_company": "",
        "seat_limit": 5,
        "contract_term": ContractTerm.MONTHLY,
        "subscription_status": SubscriptionStatus.TRIAL,
        "contract_start": date(2026, 11, 1),
        "renewal_date": date(2026, 12, 1),
        "features": ["claims", "training", "library", "passport"],
        "claim_prefix": "SMB",
    },
]

# Username, first name, role, organization.
DEMO_USERS = [
    ("om", "Om", Role.ADMIN, "AGS Health"),
    ("james", "James", Role.SPECIALIST, "AGS Health"),
    ("flora", "Flora", Role.WORKER, "AGS Health"),
    ("kevin", "Kevin", Role.WORKER, "AGS Health"),
    ("cassandra", "Cassandra", Role.WORKER, "AGS Health"),
    ("steven", "Steven", Role.ADMIN, "Summit Medical Billing"),
    ("kaua", "Kaua", Role.WORKER, "Summit Medical Billing"),
]

# Fictional patients for Cassandra's past claims, so they never match the sample claims' patients.
HISTORY_PATIENTS = [
    ("Ava", "Lindgren"), ("Marcus", "Bell"), ("Rosa", "Medina"), ("Theo", "Park"), ("Iris", "Calloway"),
    ("Grant", "Hughes"), ("Mina", "Sato"), ("Felix", "Romero"), ("June", "Whitaker"), ("Omar", "Haddad"),
    ("Lena", "Novak"), ("Caleb", "Frost"), ("Sofia", "Duarte"), ("Reid", "Morrow"), ("Hazel", "Quinn"),
    ("Victor", "Lam"), ("Nadia", "Petrov"), ("Silas", "Ward"), ("Elise", "Moreau"), ("Jonah", "Prescott"),
]  # fmt: skip
# Which of Cassandra's past claims she got wrong: 18 of 20 correct, so she is ready for promotion.
HISTORY_MISSES = {4, 13}
MINIMAL_AREAS = [Category.ELIGIBILITY, Category.PRIOR_AUTH, Category.CODE_MATCHING, Category.MODIFIERS]


class Command(BaseCommand):
    help = "Delete the demo data and load it again. Safe to run any number of times."

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD")
        if not password:
            raise CommandError("Set DEMO_PASSWORD in .env before seeding.")

        for model in (TrainingAttempt, Attempt, SkillRecord, CaseEntry, HelpRequest, AIReview, ClaimEvent, Claim, PayerRule):
            model.objects.all().delete()
        User = get_user_model()
        # Every demo account is recreated. Django superusers are left alone.
        User.objects.filter(is_superuser=False).delete()
        Organization.objects.all().delete()

        organizations = {item["name"]: Organization.objects.create(**item) for item in ORGANIZATIONS}
        users = {}
        for username, first_name, role, organization in DEMO_USERS:
            user = User.objects.create_user(username, password=password, first_name=first_name)
            Profile.objects.create(user=user, role=role, organization=organizations[organization])
            users[username] = user

        data = settings.BASE_DIR / "data"
        rules = [
            PayerRule(
                payer_name=row["payer_name"],
                rule_type=row["rule_type"],
                rule=row["rule"],
                filing_limit_days=int(row["filing_limit_days"]) if row["filing_limit_days"] else None,
                source=row["source"],
            )
            for row in read_csv(data / "demo_payer_rules.csv")
        ]
        PayerRule.objects.bulk_create(rules)

        # Saved one by one, in file order, so an earlier row is always the earlier claim.
        ags, summit = organizations["AGS Health"], organizations["Summit Medical Billing"]
        rows = read_csv(data / "sample_claims.csv")
        for row in rows:
            claim_from_row(row, assigned_to=users["flora"], organization=ags).save()
        summit_rows = read_csv(data / "summit_claims.csv")
        for row in summit_rows:
            claim_from_row(row, assigned_to=users["kaua"], organization=summit).save()
        self.add_history(users["cassandra"], ags, rows)
        ticket = Ticket.objects.create(
            organization=ags, specialist=users["james"], opened_by=users["james"], subject="More time for new hire reviews"
        )
        TicketMessage.objects.create(
            ticket=ticket,
            author=users["james"],
            body="Help requests from new workers are taking most of my mornings. Can we set aside time each week for reviews?",
        )

        call_command("load_training", stdout=self.stdout)
        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {len(ORGANIZATIONS)} organizations, {len(rows) + len(summit_rows)} claims, and "
                f"{len(rules)} payer rules. Users: {', '.join(username for username, *_ in DEMO_USERS)}."
            )
        )

    def add_history(self, worker, organization, rows):
        """Give Cassandra twenty finished, scored claims, so she shows as ready for promotion."""
        for number, (row, (first, last)) in enumerate(zip(rows, HISTORY_PATIENTS)):
            claim = claim_from_row(
                {**row, "claim_id": f"CLM-{901 + number:04d}", "patient_first": first, "patient_last": last, "status": "new"},
                assigned_to=worker,
                organization=organization,
            )
            claim.date_of_service = date(2026, 8, 3) + timedelta(days=number * 2)
            claim.work_status = WorkStatus.PAID if number not in HISTORY_MISSES else WorkStatus.CLOSED
            claim.denial_code = claim.denial_reason = ""
            claim.scored = True
            claim.save()
            category = claim.expected_category if claim.expected_category in Category.values else Attempt.NO_CATEGORY
            Attempt.objects.create(
                worker=worker, claim=claim, category=category, action_taken=FinalAction.SUBMIT, correct=number not in HISTORY_MISSES
            )
        for category in Category.values:
            attempts = Attempt.objects.filter(worker=worker, category=category)
            SkillRecord.objects.create(
                worker=worker,
                category=category,
                help_level=HelpLevel.MINIMAL if category in MINIMAL_AREAS else HelpLevel.GUIDED,
                attempts=attempts.count(),
                correct=attempts.filter(correct=True).count(),
            )
