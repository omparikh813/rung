"""Tickets and messages between an organization's specialists and its admins. Workers are not part of this."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..decorators import role_required
from ..models import Role, Ticket, TicketMessage, TicketStatus
from ..organizations import is_admin, organization_of


def tickets_for(user):
    """An admin sees every conversation in the organization. A specialist sees only their own."""
    tickets = Ticket.objects.filter(organization=organization_of(user)).select_related("specialist", "opened_by")
    return tickets if is_admin(user) else tickets.filter(specialist=user)


def needs_reply(user):
    """Open conversations where the last word came from someone else."""
    count = 0
    for ticket in tickets_for(user).filter(status=TicketStatus.OPEN).prefetch_related("messages"):
        last = list(ticket.messages.all())[-1:] or None
        if last and last[0].author_id != user.pk:
            count += 1
    return count


def specialists(organization):
    return (
        get_user_model()
        .objects.filter(profile__organization=organization, profile__role=Role.SPECIALIST, is_active=True)
        .order_by("first_name", "username")
    )


@role_required(Role.SPECIALIST)
def ticket_list(request):
    org = organization_of(request.user)
    admin = is_admin(request.user)
    error = ""
    if request.method == "POST":
        subject = request.POST.get("subject", "").strip()
        body = request.POST.get("body", "").strip()
        if admin:
            specialist = specialists(org).filter(pk=request.POST.get("specialist") or 0).first()
        else:
            specialist = request.user
        if not (subject and body and specialist):
            error = "Fill in every field before sending."
        else:
            ticket = Ticket.objects.create(organization=org, specialist=specialist, opened_by=request.user, subject=subject[:150])
            TicketMessage.objects.create(ticket=ticket, author=request.user, body=body)
            name = specialist.first_name or specialist.username
            messages.success(request, f"Message sent to {name}." if admin else "Ticket sent to your admin.")
            return redirect("ticket_detail", pk=ticket.pk)
    rows = []
    for ticket in tickets_for(request.user).prefetch_related("messages__author"):
        thread = list(ticket.messages.all())
        last = thread[-1] if thread else None
        rows.append({"ticket": ticket, "last": last, "count": len(thread), "waiting": bool(last) and last.author_id != request.user.pk and ticket.status == TicketStatus.OPEN})
    open_count = sum(row["ticket"].status == TicketStatus.OPEN for row in rows)
    context = {
        "rows": rows,
        "admin": admin,
        "error": error,
        "specialists": specialists(org) if admin else [],
        "form": {"subject": request.POST.get("subject", ""), "body": request.POST.get("body", ""), "specialist": request.POST.get("specialist", "")},
        "tiles": [
            {"icon": "messages-square", "label": "Open", "value": open_count},
            {"icon": "message-square", "label": "Waiting on you", "value": sum(row["waiting"] for row in rows)},
            {"icon": "circle-check", "label": "Closed", "value": len(rows) - open_count},
        ],
    }
    return render(request, "core/tickets.html", context)


@role_required(Role.SPECIALIST)
def ticket_detail(request, pk):
    ticket = get_object_or_404(tickets_for(request.user), pk=pk)
    if request.method == "POST":
        if ticket.status != TicketStatus.OPEN:
            raise PermissionDenied
        body = request.POST.get("body", "").strip()
        if body:
            TicketMessage.objects.create(ticket=ticket, author=request.user, body=body)
            ticket.save(update_fields=["updated_at"])
            messages.success(request, "Reply sent.")
            return redirect("ticket_detail", pk=ticket.pk)
        messages.error(request, "Write a reply before sending.")
    thread = ticket.messages.select_related("author", "author__profile")
    return render(request, "core/ticket_detail.html", {"ticket": ticket, "thread": thread, "admin": is_admin(request.user)})


@require_POST
@role_required(Role.ADMIN)
def ticket_status(request, pk):
    """Admins close a conversation when it is done, or reopen it."""
    ticket = get_object_or_404(tickets_for(request.user), pk=pk)
    ticket.status = TicketStatus.CLOSED if ticket.status == TicketStatus.OPEN else TicketStatus.OPEN
    ticket.save(update_fields=["status", "updated_at"])
    messages.success(request, "Conversation closed." if ticket.status == TicketStatus.CLOSED else "Conversation reopened.")
    return redirect("ticket_detail", pk=ticket.pk)
