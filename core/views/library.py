from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..decorators import role_required, user_role
from ..forms import CaseEntryForm
from ..models import CaseEntry, Category, Role

EVERYONE = (Role.WORKER, Role.SPECIALIST)


def can_change(user, entry):
    """Specialists can edit and delete the entries they created."""
    return user_role(user) == Role.SPECIALIST and entry.created_by_id == user.pk


def own_entry(request, pk):
    entry = get_object_or_404(CaseEntry, pk=pk)
    if not can_change(request.user, entry):
        raise PermissionDenied
    return entry


@role_required(*EVERYONE)
def library(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    payer = request.GET.get("payer", "")
    entries = CaseEntry.objects.select_related("created_by")
    if query:
        entries = entries.filter(
            Q(title__icontains=query) | Q(problem__icontains=query) | Q(fix__icontains=query) | Q(codes__icontains=query)
        )
    if category in Category.values:
        entries = entries.filter(category=category)
    if payer:
        entries = entries.filter(payer_name=payer)
    context = {
        "entries": entries,
        "query": query,
        "category": category,
        "payer": payer,
        "categories": Category.choices,
        "payers": CaseEntry.objects.exclude(payer_name="").values_list("payer_name", flat=True).distinct().order_by("payer_name"),
        "filtered": bool(query or category or payer),
    }
    template = "core/partials/library_cards.html" if request.headers.get("HX-Request") else "core/library_list.html"
    return render(request, template, context)


@role_required(*EVERYONE)
def library_detail(request, pk):
    entry = get_object_or_404(CaseEntry.objects.select_related("created_by"), pk=pk)
    return render(request, "core/library_detail.html", {"entry": entry, "can_change": can_change(request.user, entry)})


@role_required(Role.SPECIALIST)
def library_edit(request, pk):
    entry = own_entry(request, pk)
    form = CaseEntryForm(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Case Library entry saved.")
        return redirect("library_detail", pk=entry.pk)
    return render(request, "core/library_form.html", {"entry": entry, "form": form})


@require_POST
@role_required(Role.SPECIALIST)
def library_delete(request, pk):
    own_entry(request, pk).delete()
    messages.success(request, "Case Library entry deleted.")
    return redirect("library")
