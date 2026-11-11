"""Reset the demo: delete demo data, load both CSV files, and create maria and dan."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.claims import claim_from_row, read_csv
from core.models import (
    AIReview,
    Attempt,
    CaseEntry,
    Claim,
    ClaimEvent,
    HelpRequest,
    PayerRule,
    Profile,
    Role,
    SkillRecord,
)

DEMO_USERS = [("maria", "Maria", Role.WORKER), ("dan", "Dan", Role.SPECIALIST)]


class Command(BaseCommand):
    help = "Delete the demo data and load it again. Safe to run any number of times."

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD")
        if not password:
            raise CommandError("Set DEMO_PASSWORD in .env before seeding.")

        for model in (Attempt, SkillRecord, CaseEntry, HelpRequest, AIReview, ClaimEvent, Claim, PayerRule):
            model.objects.all().delete()

        User = get_user_model()
        users = {}
        for username, first_name, role in DEMO_USERS:
            user, _ = User.objects.get_or_create(username=username)
            user.first_name = first_name
            user.set_password(password)
            user.save()
            Profile.objects.update_or_create(user=user, defaults={"role": role})
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
        rows = read_csv(data / "sample_claims.csv")
        for row in rows:
            claim_from_row(row, assigned_to=users["maria"]).save()

        self.stdout.write(
            self.style.SUCCESS(f"Loaded {len(rows)} claims and {len(rules)} payer rules. Users: maria, dan.")
        )
