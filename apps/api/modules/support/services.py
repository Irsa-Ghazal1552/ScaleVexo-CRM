from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from modules.common import access, audit
from modules.common.errors import BusinessRuleError, require_version
from modules.identity.models import Membership

from .models import Ticket, TicketEvent, TicketNote

S = Ticket.Status

TRANSITIONS = {
    S.NEW: {S.TRIAGED, S.IN_PROGRESS},
    S.TRIAGED: {S.IN_PROGRESS, S.WAITING_CUSTOMER, S.WAITING_INTERNAL, S.RESOLVED},
    S.IN_PROGRESS: {S.WAITING_CUSTOMER, S.WAITING_INTERNAL, S.RESOLVED, S.TRIAGED},
    S.WAITING_CUSTOMER: {S.IN_PROGRESS, S.RESOLVED},
    S.WAITING_INTERNAL: {S.IN_PROGRESS, S.RESOLVED},
    S.RESOLVED: {S.CLOSED, S.TRIAGED},  # reopening returns to triage
    S.CLOSED: {S.TRIAGED},
}


def _event(actor, ticket, from_status, note=""):
    TicketEvent.objects.create(
        workspace=actor.workspace, ticket=ticket, from_status=from_status, to_status=ticket.status, actor=actor, note=note,
        snapshot={"resolution_note": ticket.resolution_note, "closure_test_result": ticket.closure_test_result,
                  "severity": ticket.severity, "owner": str(ticket.owner_id)},
    )


def _member(actor, member_id, field):
    if not member_id:
        return None
    m = Membership.objects.filter(workspace=actor.workspace, pk=member_id, status="active").first()
    if m is None:
        raise BusinessRuleError("Choose an active team member.", fields={field: ["Invalid"]})
    return m


def create_ticket(actor, data):
    title = (data.get("title") or "").strip()
    if not title:
        raise BusinessRuleError("Give the ticket a title.", fields={"title": ["Required"]})
    severity = data.get("severity") or Ticket.Severity.MEDIUM
    if severity not in Ticket.Severity.values:
        raise BusinessRuleError("Unknown severity.")
    client = project = None
    if data.get("project_id"):
        project = access.projects_for(actor).filter(pk=data["project_id"]).first()
        if project is None:
            raise BusinessRuleError("Project not found.")
        client = project.client
    if data.get("client_id"):
        client = access.clients_for(actor).filter(pk=data["client_id"]).first()
        if client is None:
            raise BusinessRuleError("Client not found.")
    kind = data.get("kind") or ("client" if client else "internal")
    owner = _member(actor, data.get("owner_id"), "owner_id")
    for attempt in range(3):
        try:
            with transaction.atomic():
                number = (Ticket.objects.filter(workspace=actor.workspace).aggregate(n=Max("number"))["n"] or 0) + 1
                ticket = Ticket.objects.create(
                    workspace=actor.workspace, number=number, title=title, kind=kind,
                    description=(data.get("description") or "").strip(), client=client, project=project,
                    severity=severity, owner=owner, created_by=actor, next_action=(data.get("next_action") or "").strip(),
                    status=S.TRIAGED if owner else S.NEW,
                )
                _event(actor, ticket, "", "Created")
                break
        except IntegrityError:
            if attempt == 2:
                raise
    audit.record(actor.workspace, actor, "ticket.created", ticket, f"Ticket #{ticket.number}: {title}")
    if ticket.severity == Ticket.Severity.CRITICAL:
        from modules.automation.engine import critical_ticket_alert

        critical_ticket_alert(ticket)
    return ticket


def update_ticket(actor, ticket, data):
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
        require_version(locked, data.get("version"))
        changes = {}
        for f in ("title", "description", "next_action"):
            if f in data:
                changes[f] = True
                setattr(locked, f, (data[f] or "").strip())
        was_critical = locked.severity == Ticket.Severity.CRITICAL
        if "severity" in data:
            if data["severity"] not in Ticket.Severity.values:
                raise BusinessRuleError("Unknown severity.")
            locked.severity = data["severity"]
            changes["severity"] = data["severity"]
        if "owner_id" in data:
            locked.owner = _member(actor, data["owner_id"], "owner_id")
            changes["owner"] = str(locked.owner_id)
            if locked.owner and locked.status == S.NEW:
                prev = locked.status
                locked.status = S.TRIAGED
                _event(actor, locked, prev, "Owner assigned")
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "ticket.updated", locked, f"Updated ticket #{locked.number}", changes)
    if not was_critical and locked.severity == Ticket.Severity.CRITICAL:
        from modules.automation.engine import critical_ticket_alert

        critical_ticket_alert(locked)
    return locked


def transition_ticket(actor, ticket, to_status, data):
    if to_status not in S.values:
        raise BusinessRuleError("Unknown status.")
    with transaction.atomic():
        locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
        require_version(locked, data.get("version"))
        previous = locked.status
        if to_status not in TRANSITIONS[previous]:
            raise BusinessRuleError(f"A ticket cannot move from {previous} to {to_status}.")
        note = (data.get("note") or "").strip()
        if to_status != S.NEW and not locked.owner_id and not data.get("owner_id"):
            raise BusinessRuleError("Assign an owner first.", fields={"owner_id": ["Required"]})
        if data.get("owner_id"):
            locked.owner = _member(actor, data["owner_id"], "owner_id")
        if to_status in (S.WAITING_CUSTOMER, S.WAITING_INTERNAL):
            reason = (data.get("waiting_reason") or "").strip()
            review = data.get("waiting_review_at")
            nxt = data.get("waiting_next_owner_id")
            if not reason or not review or not nxt:
                raise BusinessRuleError("Waiting needs a reason, the next owner and a review time.",
                                        fields={"waiting_reason": ["Required"], "waiting_next_owner_id": ["Required"], "waiting_review_at": ["Required"]})
            from modules.crm.services import _parse_dt

            locked.waiting_reason = reason
            locked.waiting_next_owner = _member(actor, nxt, "waiting_next_owner_id")
            locked.waiting_review_at = _parse_dt(review, actor.workspace)
        elif previous in (S.WAITING_CUSTOMER, S.WAITING_INTERNAL):
            locked.waiting_reason = ""
            locked.waiting_next_owner = None
            locked.waiting_review_at = None
        if to_status == S.RESOLVED:
            res = (data.get("resolution_note") or "").strip()
            test = (data.get("closure_test_result") or "").strip()
            if not res or not test:
                raise BusinessRuleError("A resolution note and the closure test result are required.",
                                        fields={"resolution_note": ["Required"], "closure_test_result": ["Required"]})
            locked.resolution_note, locked.closure_test_result = res, test
            locked.resolved_at = timezone.now()
        if to_status == S.CLOSED:
            locked.closed_at = timezone.now()
        if previous in (S.RESOLVED, S.CLOSED) and to_status == S.TRIAGED:
            if not note:
                raise BusinessRuleError("Explain why the ticket is being reopened.", fields={"note": ["Required"]})
            locked.reopen_count += 1
            # previous resolution stays in TicketEvent snapshots; clear current fields for the new cycle
            _event(actor, locked, previous, f"Reopen requested: {note}")
            locked.resolution_note = ""
            locked.closure_test_result = ""
            locked.resolved_at = None
            locked.closed_at = None
        locked.status = to_status
        locked.bump()
        locked.save()
        _event(actor, locked, previous, note)
        audit.record(actor.workspace, actor, "ticket.status", locked, f"Ticket #{locked.number}: {previous} → {to_status}", {"note": note})
    return locked


def add_note(actor, ticket, data):
    body = (data.get("body") or "").strip()
    if not body:
        raise BusinessRuleError("Write the note.", fields={"body": ["Required"]})
    visibility = data.get("visibility") or TicketNote.Visibility.INTERNAL
    if visibility not in TicketNote.Visibility.values:
        raise BusinessRuleError("Unknown visibility.")
    note = TicketNote.objects.create(workspace=actor.workspace, ticket=ticket, author=actor, body=body, visibility=visibility)
    audit.record(actor.workspace, actor, "ticket.note", ticket, f"Note on ticket #{ticket.number} ({visibility})")
    return note
