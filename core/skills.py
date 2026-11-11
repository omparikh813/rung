"""Fading help: each worker has a help level per skill category."""

from .models import HelpLevel, SkillRecord


def help_levels(worker):
    """The worker's help level in each category they have a record for. Missing means FULL."""
    return dict(SkillRecord.objects.filter(worker=worker).values_list("category", "help_level"))


def help_level(levels, category):
    return levels.get(category, HelpLevel.FULL)
