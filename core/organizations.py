"""Organizations: the company directory, seat tiers, and finding a user's organization.

This is a demo. There are no prices or payments, only seats, tiers, and contract details.
"""

from .models import REVIEWER_ROLES, Role

# Suggested companies for onboarding, from Black Book Market Research's Q4 2025
# Cross-Ancillary / Enterprise Ambulatory Ancillary RCM ranking. Being listed here
# does not mean a company has a RUNG contract.
DIRECTORY = [
    "XIFIN", "Optum", "AGS Health", "AKASA", "FinThrive", "athenahealth", "SYNERGEN",
    "Tebra (Kareo)", "TruBridge", "Medsphere / ChartLogic", "AdvancedMD", "Ensemble Health Partners",
    "Conifer Health Solutions", "Guidehouse", "Sagility", "GeBBS Healthcare Solutions",
    "Omega Healthcare", "Access Healthcare", "NIMBLE", "MED-METRIX Health",
]  # fmt: skip

# Seat tiers: the largest seat count in the tier, its name, and the suggested plan. Not prices.
TIERS = [
    (5, "Starter", "Basic"),
    (20, "Small Business", "Team"),
    (50, "Growth", "Professional"),
    (100, "Business", "Business"),
    (250, "Enterprise", "Enterprise"),
    (500, "Large Enterprise", "Custom"),
    (None, "Corporate", "Negotiated contract"),
]

SEAT_RANGES = ["1–5", "6–20", "21–50", "51–100", "101–250", "251–500", "500+"]

FEATURES = {
    "claims": "AI claim review",
    "training": "Daily Training",
    "library": "Case Library",
    "passport": "Skill Passport",
    "export": "ANSI X12 837 export",
    "analytics": "Organization analytics",
}


def tier_for(seats):
    """The tier name and suggested plan for a number of seats."""
    for largest, name, plan in TIERS:
        if largest is None or seats <= largest:
            return name, plan


def organization_of(user):
    profile = getattr(user, "profile", None)
    return profile.organization if profile else None


def is_reviewer(user):
    """Specialists and admins review workers' claims and coach them."""
    profile = getattr(user, "profile", None)
    return bool(profile) and profile.role in REVIEWER_ROLES


def is_admin(user):
    profile = getattr(user, "profile", None)
    return bool(profile) and profile.role == Role.ADMIN
