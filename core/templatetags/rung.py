"""Template helpers shared by every RUNG template."""

import re
from functools import lru_cache

from django import template
from django.contrib.staticfiles import finders
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@lru_cache(maxsize=None)
def _icon_body(name):
    path = finders.find(f"icons/{name}.svg")
    if not path:
        raise template.TemplateSyntaxError(f"Unknown icon: {name}")
    with open(path, encoding="utf-8") as handle:
        svg = handle.read()
    svg = svg[svg.index("<svg"):]
    svg = re.sub(r'\s(class|width|height)="[^"]*"', "", svg, count=3)
    return re.sub(r"\s+", " ", svg).strip()


@register.simple_tag
def icon(name, css="size-4"):
    """Inline a Lucide icon from static/icons so it takes the text color."""
    svg = _icon_body(name).replace(
        "<svg", f'<svg class="shrink-0 {escape(css)}" aria-hidden="true" focusable="false"', 1
    )
    return mark_safe(svg)


@register.filter
def get_item(mapping, key):
    """Look up a dict value by a variable key."""
    return mapping.get(key) if mapping else None


@register.filter
def field_wrap(name):
    """Grid classes for a claim form field. The date of service gets a row to itself."""
    return "@md:col-span-2 @md:max-w-[calc(50%-0.5rem)]" if name == "date_of_service" else ""


CATEGORY_ICONS = {
    "eligibility": "shield-check",
    "prior_auth": "badge-check",
    "code_matching": "scan-search",
    "modifiers": "zap",
    "documentation": "file-check-2",
    "filing_rules": "calendar-clock",
}


@register.filter
def category_icon(category):
    """The icon for a skill category."""
    return CATEGORY_ICONS.get(category, "sparkle")


@register.filter
def category_tone(category):
    """The pastel background class for a skill category."""
    return f"tone-{category}" if category in CATEGORY_ICONS else "bg-sage-soft"


@register.filter
def plain_fields(text):
    """Show form labels in place of field names such as icd10_primary."""
    from ..reviews import plain_fields as swap

    return swap(text)
