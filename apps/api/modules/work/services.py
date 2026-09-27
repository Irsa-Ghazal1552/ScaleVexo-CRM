from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from modules.common import access, audit
from modules.common.errors import BusinessRuleError, require_version
from modules.identity.models import DELIVERY_ROLES, Membership, Role

from .models import (
    Client, Handover, Milestone, MilestoneEvent, MilestoneStatus, Project, ProjectChange, ProjectTemplate,
    Task, TaskReschedule,
)


def _member(actor, member_id, field="owner_id", require_active=True):
    if not member_id:
        return None
    m = Membership.objects.filter(workspace=actor.workspace, pk=member_id).first()
    if m is None:
        raise BusinessRuleError("Choose a valid team member.", fields={field: ["Unknown member"]})
    if require_active and not m.is_active:
        raise BusinessRuleError("Suspended members cannot receive work.", fields={field: ["Suspended member"]})
    return m


def _dt(actor, value, field="due_at"):
    from modules.crm.services import _parse_dt

    try:
        return _parse_dt(value, actor.workspace)
    except ValueError:
        raise BusinessRuleError("Enter a valid date and time.", fields={field: ["Invalid date"]})


# ---------------------------------------------------------------- tasks (CRM05)
def create_task(actor, data, check_scope=True, rule_code=""):
    ws = actor.workspace
    title = (data.get("title") or "").strip()
    if not title:
        raise BusinessRuleError("Give the task a title.", fields={"title": ["Required"]})
    owner = _member(actor, data.get("owner_id") or actor.pk)
    due = data.get("due_at")
    due = due if hasattr(due, "tzinfo") else _dt(actor, due)
    if due is None:
        raise BusinessRuleError("A task needs a due date and time.", fields={"due_at": ["Required"]})
    if check_scope and owner.pk != actor.pk and owner not in access.team_members_visible(actor) and actor.role != Role.OWNER:
        raise BusinessRuleError("You can only assign tasks to yourself or people you manage.")
    links = {}
    if check_scope:
        scopes = {
            "lead_id": access.leads_for, "opportunity_id": access.opportunities_for, "client_id": access.clients_for,
            "project_id": access.projects_for, "ticket_id": access.tickets_for,
        }
        for key, scope in scopes.items():
            if data.get(key):
                obj = scope(actor).filter(pk=data[key]).first()
                if obj is None:
                    raise BusinessRuleError("The linked record was not found.")
                links[key.replace("_id", "")] = obj
        if data.get("milestone_id"):
            ms = Milestone.objects.filter(workspace=ws, pk=data["milestone_id"], project__in=access.projects_for(actor)).first()
            if ms is None:
                raise BusinessRuleError("The linked milestone was not found.")
            links["milestone"] = ms
            links.setdefault("project", ms.project)
    else:
        for key in ("lead_id", "opportunity_id", "client_id", "project_id", "ticket_id", "milestone_id"):
            if data.get(key):
                links[key] = data[key]
    task = Task.objects.create(
        workspace=ws, title=title, description=(data.get("description") or "").strip(),
        kind=data.get("kind") if data.get("kind") in Task.Kind.values else Task.Kind.TASK,
        owner=owner, due_at=due, original_due_at=due, created_by=actor, created_by_rule=rule_code, **links,
    )
    audit.record(ws, actor, "task.created", task, f"Task '{title}' for {owner.display_name}")
    return task


def _can_act_on_task(actor, task):
    if task.owner_id == actor.pk or actor.role == Role.OWNER:
        return True
    return access.team_members_visible(actor).filter(pk=task.owner_id).exists() and actor.role in (
        Role.SALES_MANAGER, Role.DELIVERY_MANAGER)


def complete_task(actor, task, data):
    if not _can_act_on_task(actor, task):
        raise BusinessRuleError("Only the owner or their manager can complete this task.")
    if task.status in (Task.Status.DONE, Task.Status.CANCELLED):
        raise BusinessRuleError("This task is already closed.")
    outcome = (data.get("outcome") or "").strip()
    if not outcome:
        raise BusinessRuleError("Record the outcome before completing.", fields={"outcome": ["Required"]})
    next_title = (data.get("next_action") or "").strip()
    stop_reason = (data.get("stop_reason") or "").strip()
    if task.kind == Task.Kind.FOLLOW_UP and not next_title and not stop_reason:
        raise BusinessRuleError("Schedule the next action or give a reason to stop following up.",
                                code="next_action_required", fields={"next_action": ["Next action or stop reason required"]})
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        require_version(locked, data.get("version"))
        locked.status = Task.Status.DONE
        locked.outcome = outcome
        locked.stop_reason = stop_reason
        locked.completed_at = timezone.now()
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "task.completed", locked, f"Completed '{locked.title}'", {"outcome": outcome})
        next_task = None
        if next_title:
            due = _dt(actor, data.get("next_action_due"), "next_action_due")
            if due is None:
                raise BusinessRuleError("Choose when the next action is due.", fields={"next_action_due": ["Required"]})
            next_task = create_task(actor, {
                "title": next_title, "kind": locked.kind, "owner_id": locked.owner_id, "due_at": due,
                "lead_id": locked.lead_id, "opportunity_id": locked.opportunity_id, "client_id": locked.client_id,
                "project_id": locked.project_id, "milestone_id": locked.milestone_id, "ticket_id": locked.ticket_id,
            }, check_scope=False)
            _sync_next_action(locked, next_title, due)
        elif stop_reason:
            _sync_next_action(locked, "", None)
    return locked, next_task


def _sync_next_action(task, title, due):
    from modules.crm.models import Lead, Opportunity

    if task.opportunity_id:
        Opportunity.objects.filter(pk=task.opportunity_id).update(next_action=title, next_action_due=due)
    elif task.lead_id:
        Lead.objects.filter(pk=task.lead_id).update(next_action=title, next_action_due=due)


def reschedule_task(actor, task, data):
    if not _can_act_on_task(actor, task):
        raise BusinessRuleError("Only the owner or their manager can reschedule this task.")
    if task.status in (Task.Status.DONE, Task.Status.CANCELLED):
        raise BusinessRuleError("Closed tasks cannot be rescheduled.")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BusinessRuleError("A reason is required to reschedule.", fields={"reason": ["Required"]})
    new_due = _dt(actor, data.get("due_at"))
    if new_due is None:
        raise BusinessRuleError("Choose the new due time.", fields={"due_at": ["Required"]})
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        require_version(locked, data.get("version"))
        TaskReschedule.objects.create(workspace=actor.workspace, task=locked, from_due=locked.due_at, to_due=new_due, reason=reason, actor=actor)
        old = locked.due_at
        locked.due_at = new_due
        locked.reschedule_count += 1
        locked.bump()
        locked.save()
        if locked.kind == Task.Kind.FOLLOW_UP:
            _sync_next_action(locked, locked.title, new_due)
        audit.record(actor.workspace, actor, "task.rescheduled", locked, f"Rescheduled '{locked.title}'",
                     {"from": old.isoformat(), "to": new_due.isoformat(), "reason": reason})
    return locked


def set_task_blocked(actor, task, data, blocked=True):
    if not _can_act_on_task(actor, task):
        raise BusinessRuleError("Only the owner or their manager can change this task.")
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        require_version(locked, data.get("version"))
        if blocked:
            reason = (data.get("reason") or "").strip()
            if not reason:
                raise BusinessRuleError("Describe what is blocking the task.", fields={"reason": ["Required"]})
            locked.status = Task.Status.BLOCKED
            locked.blocked_reason = reason
        else:
            locked.status = Task.Status.OPEN
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "task.blocked" if blocked else "task.unblocked", locked, f"'{locked.title}' {'blocked' if blocked else 'unblocked'}")
    return locked


def cancel_task(actor, task, data):
    if not _can_act_on_task(actor, task):
        raise BusinessRuleError("Only the owner or their manager can cancel this task.")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BusinessRuleError("A reason is required to cancel.", fields={"reason": ["Required"]})
    with transaction.atomic():
        locked = Task.objects.select_for_update().get(pk=task.pk)
        require_version(locked, data.get("version"))
        locked.status = Task.Status.CANCELLED
        locked.stop_reason = reason
        locked.completed_at = timezone.now()
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "task.cancelled", locked, f"Cancelled '{locked.title}'", {"reason": reason})
    return locked


# ---------------------------------------------------------------- win + conversion (CRM07)
@transaction.atomic
def win_opportunity(actor, opp, data):
    from modules.automation.engine import raise_alert, record_execution
    from modules.crm.models import Opportunity, Stage
    from modules.crm.services import _history

    locked = Opportunity.objects.select_for_update().get(pk=opp.pk)
    if locked.stage == Stage.WON:
        return locked  # retry: conversion already happened exactly once
    require_version(locked, data.get("version"))
    if locked.stage == Stage.LOST:
        raise BusinessRuleError("Reopen the lost deal before closing it as won.")
    scope = (data.get("scope") or "").strip()
    commercial_reference = (data.get("commercial_reference") or "").strip()
    decision = (data.get("commercial_decision") or "").strip()
    errors = {}
    if not scope:
        errors["scope"] = ["Accepted scope evidence is required"]
    if not commercial_reference:
        errors["commercial_reference"] = ["Contract, PO or signed proposal reference is required"]
    if not decision:
        errors["commercial_decision"] = ["Record the commercial decision (who approved, on what terms)"]
    delivery_owner = None
    if not data.get("delivery_owner_id"):
        errors["delivery_owner_id"] = ["Choose the delivery owner"]
    else:
        delivery_owner = Membership.objects.filter(workspace=actor.workspace, pk=data["delivery_owner_id"]).first()
        if delivery_owner is None:
            errors["delivery_owner_id"] = ["Unknown member"]
        elif delivery_owner.role not in (Role.OWNER, Role.DELIVERY_MANAGER, Role.DELIVERY_EMPLOYEE):
            errors["delivery_owner_id"] = ["The delivery owner must be on the delivery team"]
    if errors:
        raise BusinessRuleError("Closing as won needs accepted scope, a commercial decision and a delivery owner.",
                                code="won_requirements", fields=errors)

    previous = locked.stage
    locked.stage = Stage.WON
    locked.stage_changed_at = timezone.now()
    locked.closed_at = timezone.now()
    locked.commercial_decision = decision
    if not locked.scope_reference:
        locked.scope_reference = commercial_reference
    locked.bump()
    locked.save()
    _history(actor, "opportunity", locked, previous, Stage.WON, decision)

    client = Client.objects.filter(workspace=actor.workspace, primary_contact=locked.contact).first()
    if client is None:
        client = Client.objects.create(
            workspace=actor.workspace, name=locked.contact.company_name or locked.contact.name or locked.title,
            primary_contact=locked.contact, account_owner=locked.owner,
        )
    status = Handover.Status.PENDING if delivery_owner.is_available() else Handover.Status.EXCEPTION
    handover = Handover.objects.create(
        workspace=actor.workspace, opportunity=locked, client=client, scope=scope,
        exclusions=(data.get("exclusions") or "").strip(), client_contacts=(data.get("client_contacts") or "").strip(),
        commercial_reference=commercial_reference, delivery_owner=delivery_owner,
        promised_start=parse_date(data["promised_start"]) if data.get("promised_start") else None,
        promised_end=parse_date(data["promised_end"]) if data.get("promised_end") else None,
        promised_dates_note=(data.get("promised_dates_note") or "").strip(), status=status, created_by=actor,
    )
    template = None
    if data.get("template_id"):
        template = ProjectTemplate.objects.filter(workspace=actor.workspace, pk=data["template_id"]).first()
    template = template or ProjectTemplate.objects.filter(workspace=actor.workspace, is_default=True).first() \
        or ProjectTemplate.objects.filter(workspace=actor.workspace).first()
    project = create_project_from_template(actor, client, handover, template, delivery_owner)
    record_execution(actor.workspace, "A05", f"won:{locked.pk}", "opportunity", locked.pk, "Onboarding created and acceptance requested")
    recipients = [delivery_owner] if status == Handover.Status.PENDING else _delivery_managers(actor.workspace)
    raise_alert(
        actor.workspace, "A05", recipients, "handover", handover.pk,
        f"Handover awaiting acceptance: {client.name}" if status == Handover.Status.PENDING else f"Handover needs a delivery owner: {client.name}",
        f"Deal '{locked.title}' was won by {actor.display_name}. Review the scope and accept or return the handover.",
        dedupe_key=f"handover:{handover.pk}", severity="warning" if status == Handover.Status.PENDING else "critical",
    )
    from modules.work.models import Task

    Task.objects.filter(opportunity=locked, status__in=["open", "blocked"]).update(
        status="cancelled", stop_reason="Deal won - handed to delivery", completed_at=timezone.now())
    audit.record(actor.workspace, actor, "opportunity.won", locked, f"Deal won: {locked.title}",
                 {"client": str(client.pk), "handover": str(handover.pk), "project": str(project.pk)})
    return locked


def _delivery_managers(workspace):
    managers = list(Membership.objects.filter(workspace=workspace, role=Role.DELIVERY_MANAGER, status="active"))
    return managers or list(Membership.objects.filter(workspace=workspace, role=Role.OWNER, status="active"))


def create_project_from_template(actor, client, handover, template, manager, name=None, kind=Project.Kind.ONBOARDING):
    start = (handover.promised_start if handover else None) or timezone.localdate()
    project = Project.objects.create(
        workspace=actor.workspace, client=client, handover=handover,
        name=name or f"Onboarding - {client.name}", kind=kind,
        status=Project.Status.PENDING_HANDOVER if handover else Project.Status.ACCEPTED,
        manager=manager, start_date=start, due_date=handover.promised_end if handover else None,
    )
    if manager:
        project.members.add(manager)
    created = []
    for index, item in enumerate((template.milestones if template else []) or []):
        ms = Milestone.objects.create(
            workspace=actor.workspace, project=project, title=item.get("title") or f"Milestone {index + 1}",
            order=index, owner=manager, due_date=start + timedelta(days=int(item.get("offset_days") or 0)),
        )
        created.append(ms)
    for index, item in enumerate((template.milestones if template else []) or []):
        for dep in item.get("depends_on") or []:
            if 0 <= int(dep) < len(created) and int(dep) != index:
                created[index].depends_on.add(created[int(dep)])
    audit.record(actor.workspace, actor, "project.created", project, f"Project {project.name} created")
    return project


def _can_decide_handover(actor, handover):
    return actor.role in (Role.OWNER, Role.DELIVERY_MANAGER) or handover.delivery_owner_id == actor.pk


@transaction.atomic
def accept_handover(actor, handover, data):
    handover = Handover.objects.select_for_update().get(pk=handover.pk)
    if not _can_decide_handover(actor, handover):
        raise BusinessRuleError("Only the delivery owner or a delivery manager can accept this handover.")
    if handover.status == Handover.Status.ACCEPTED:
        return handover
    if not handover.delivery_owner_id or not handover.delivery_owner.is_active:
        raise BusinessRuleError("Assign an active delivery owner before accepting.", fields={"delivery_owner_id": ["Required"]})
    handover.status = Handover.Status.ACCEPTED
    handover.decided_by = actor
    handover.decided_at = timezone.now()
    handover.bump()
    handover.save()
    client = handover.client
    if not client.delivery_manager_id:
        client.delivery_manager = handover.delivery_owner
        client.save(update_fields=["delivery_manager", "updated_at"])
    project = getattr(handover, "project", None)
    if project and project.status == Project.Status.PENDING_HANDOVER:
        project.status = Project.Status.ACCEPTED
        project.bump()
        project.save()
    from modules.automation.engine import resolve_alerts

    resolve_alerts(actor.workspace, f"handover:{handover.pk}", actor, "Handover accepted")
    audit.record(actor.workspace, actor, "handover.accepted", handover, f"Handover accepted for {client.name}")
    return handover


@transaction.atomic
def return_handover(actor, handover, data):
    from modules.automation.engine import raise_alert, resolve_alerts

    handover = Handover.objects.select_for_update().get(pk=handover.pk)
    if not _can_decide_handover(actor, handover):
        raise BusinessRuleError("Only the delivery owner or a delivery manager can return this handover.")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BusinessRuleError("List the missing information.", fields={"reason": ["Required"]})
    if handover.status == Handover.Status.ACCEPTED:
        raise BusinessRuleError("An accepted handover cannot be returned. Raise a scope change instead.")
    handover.status = Handover.Status.RETURNED
    handover.return_reason = reason
    handover.decided_by = actor
    handover.decided_at = timezone.now()
    handover.bump()
    handover.save()
    resolve_alerts(actor.workspace, f"handover:{handover.pk}", actor, "Returned to sales")
    owner = handover.opportunity.owner
    if owner:
        raise_alert(actor.workspace, "A05", [owner], "handover", handover.pk,
                    f"Handover returned: {handover.client.name}", f"{actor.display_name} needs: {reason}",
                    dedupe_key=f"handover-returned:{handover.pk}:{handover.version}")
    audit.record(actor.workspace, actor, "handover.returned", handover, f"Handover returned for {handover.client.name}", {"reason": reason})
    return handover


@transaction.atomic
def resubmit_handover(actor, handover, data):
    from modules.automation.engine import raise_alert, resolve_alerts

    handover = Handover.objects.select_for_update().get(pk=handover.pk)
    if actor.role not in (Role.OWNER, Role.SALES_MANAGER) and handover.opportunity.owner_id != actor.pk \
            and actor.role != Role.DELIVERY_MANAGER:
        raise BusinessRuleError("Only the deal owner or a manager can update this handover.")
    require_version(handover, data.get("version"))
    if handover.status == Handover.Status.ACCEPTED:
        raise BusinessRuleError("This handover is already accepted.")
    for f in ("scope", "exclusions", "client_contacts", "commercial_reference", "promised_dates_note"):
        if f in data:
            setattr(handover, f, (data[f] or "").strip())
    for f in ("promised_start", "promised_end"):
        if f in data:
            setattr(handover, f, parse_date(data[f]) if data[f] else None)
    if data.get("delivery_owner_id"):
        owner = _member(actor, data["delivery_owner_id"], "delivery_owner_id")
        if owner.role not in DELIVERY_ROLES and owner.role != Role.OWNER:
            raise BusinessRuleError("The delivery owner must be on the delivery team.")
        handover.delivery_owner = owner
        project = getattr(handover, "project", None)
        if project:
            project.manager = owner
            project.save(update_fields=["manager", "updated_at"])
            project.members.add(owner)
    if not handover.scope or not handover.commercial_reference:
        raise BusinessRuleError("Scope and commercial reference are required.")
    handover.status = Handover.Status.PENDING if handover.delivery_owner and handover.delivery_owner.is_available() else Handover.Status.EXCEPTION
    handover.bump()
    handover.save()
    resolve_alerts(actor.workspace, f"handover-returned:{handover.pk}", actor, "Resubmitted")
    recipients = [handover.delivery_owner] if handover.status == Handover.Status.PENDING else _delivery_managers(actor.workspace)
    raise_alert(actor.workspace, "A05", recipients, "handover", handover.pk, f"Handover resubmitted: {handover.client.name}",
                f"{actor.display_name} updated the handover. Please review it again.", dedupe_key=f"handover:{handover.pk}")
    audit.record(actor.workspace, actor, "handover.resubmitted", handover, f"Handover resubmitted for {handover.client.name}")
    return handover


# ---------------------------------------------------------------- milestones (CRM08)
def _is_reviewer(actor, project):
    return actor.role in (Role.OWNER, Role.DELIVERY_MANAGER) or project.manager_id == actor.pk


def _milestone_event(actor, ms, from_status, note=""):
    MilestoneEvent.objects.create(
        workspace=actor.workspace, milestone=ms, from_status=from_status, to_status=ms.status, actor=actor,
        note=note or "", evidence_snapshot=ms.evidence,
    )


ALLOWED = {
    MilestoneStatus.PLANNED: {MilestoneStatus.READY, MilestoneStatus.IN_PROGRESS, MilestoneStatus.CANCELLED},
    MilestoneStatus.READY: {MilestoneStatus.IN_PROGRESS, MilestoneStatus.BLOCKED, MilestoneStatus.CANCELLED, MilestoneStatus.PLANNED},
    MilestoneStatus.IN_PROGRESS: {MilestoneStatus.BLOCKED, MilestoneStatus.IN_REVIEW, MilestoneStatus.CANCELLED},
    MilestoneStatus.BLOCKED: {MilestoneStatus.IN_PROGRESS, MilestoneStatus.READY, MilestoneStatus.CANCELLED},
    MilestoneStatus.IN_REVIEW: {MilestoneStatus.ACCEPTED, MilestoneStatus.IN_PROGRESS},
    MilestoneStatus.ACCEPTED: {MilestoneStatus.IN_PROGRESS},  # reopen
    MilestoneStatus.CANCELLED: set(),
}


def transition_milestone(actor, ms, to_status, data):
    if to_status not in MilestoneStatus.values:
        raise BusinessRuleError("Unknown milestone status.")
    # Read the project fresh: the caller's copy may predate accept_handover.
    project = Project.objects.get(pk=ms.project_id)
    if project.status == Project.Status.PENDING_HANDOVER:
        raise BusinessRuleError("Accept the handover before starting delivery work.")
    with transaction.atomic():
        locked = Milestone.objects.select_for_update().get(pk=ms.pk)
        require_version(locked, data.get("version"))
        previous = locked.status
        if to_status not in ALLOWED[previous]:
            raise BusinessRuleError(f"A milestone cannot move from {previous} to {to_status}.")
        note = (data.get("note") or "").strip()
        is_owner = locked.owner_id == actor.pk or (actor in project.members.all())
        if not (is_owner or _is_reviewer(actor, project)):
            raise BusinessRuleError("Only the milestone owner, project members or the delivery manager can change it.")
        if to_status == MilestoneStatus.BLOCKED:
            desc = (data.get("blocker_description") or "").strip()
            if not desc or not data.get("blocker_next_owner_id"):
                raise BusinessRuleError("Blocked work needs a blocker description and a next owner.",
                                        fields={"blocker_description": ["Required"], "blocker_next_owner_id": ["Required"]})
            locked.blocker_description = desc
            locked.blocker_next_owner = _member(actor, data["blocker_next_owner_id"], "blocker_next_owner_id")
        if previous == MilestoneStatus.BLOCKED and to_status != MilestoneStatus.CANCELLED:
            note = note or "Unblocked"
        if to_status == MilestoneStatus.IN_REVIEW:
            evidence = (data.get("evidence") or "").strip()
            if not evidence:
                raise BusinessRuleError("Attach evidence (link or description) for the reviewer.", fields={"evidence": ["Required"]})
            locked.evidence = evidence
            locked.submitted_by = actor
            locked.submitted_at = timezone.now()
        if to_status == MilestoneStatus.ACCEPTED:
            if not _is_reviewer(actor, project):
                raise BusinessRuleError("Only an authorised reviewer (delivery manager or project manager) can accept work.")
            if locked.submitted_by_id == actor.pk and actor.role != Role.OWNER and project.manager_id != actor.pk:
                raise BusinessRuleError("You cannot accept work you submitted yourself.")
            pending = [d for d in locked.depends_on.all() if d.status != MilestoneStatus.ACCEPTED and d.status != MilestoneStatus.CANCELLED]
            if pending:
                override = (data.get("override_reason") or "").strip()
                if actor.role not in (Role.OWNER, Role.DELIVERY_MANAGER) or not override:
                    raise BusinessRuleError(
                        "Predecessor milestones are not accepted yet: " + ", ".join(p.title for p in pending)
                        + ". A delivery manager can accept with a recorded override reason.",
                        code="dependency_pending", fields={"override_reason": ["Manager override reason required"]})
                locked.override_reason = override
                note = (note + f" Override: {override}").strip()
            locked.accepted_by = actor
            locked.accepted_at = timezone.now()
        if to_status == MilestoneStatus.CANCELLED:
            reason = (data.get("cancel_reason") or "").strip()
            impact = (data.get("cancel_impact") or "").strip()
            if not reason or not impact:
                raise BusinessRuleError("Cancellation needs a reason and the impact.", fields={"cancel_reason": ["Required"], "cancel_impact": ["Required"]})
            locked.cancel_reason, locked.cancel_impact = reason, impact
        if previous == MilestoneStatus.ACCEPTED and to_status == MilestoneStatus.IN_PROGRESS:
            if not note:
                raise BusinessRuleError("A reason is required to reopen accepted work.", fields={"note": ["Required"]})
            if not _is_reviewer(actor, project):
                raise BusinessRuleError("Only a reviewer can reopen accepted work.")
            locked.reopen_count += 1
            locked.accepted_at = None
        if previous == MilestoneStatus.IN_REVIEW and to_status == MilestoneStatus.IN_PROGRESS and not note:
            raise BusinessRuleError("Tell the owner what needs to change.", fields={"note": ["Required"]})
        locked.status = to_status
        locked.bump()
        locked.save()
        _milestone_event(actor, locked, previous, note)
        _refresh_project_status(actor, project)
        audit.record(actor.workspace, actor, "milestone.status", locked, f"Milestone '{locked.title}': {previous} → {to_status}", {"note": note})
    return locked


def _refresh_project_status(actor, project):
    statuses = list(project.milestones.values_list("status", flat=True))
    if project.status in (Project.Status.PENDING_HANDOVER, Project.Status.COMPLETED):
        return
    new = project.status
    if statuses and all(s in (MilestoneStatus.ACCEPTED, MilestoneStatus.CANCELLED) for s in statuses):
        new = Project.Status.READY
    elif any(s not in (MilestoneStatus.PLANNED,) for s in statuses):
        new = Project.Status.IN_PROGRESS
    if new != project.status:
        project.status = new
        project.bump()
        project.save()


def complete_project(actor, project, data):
    if not _is_reviewer(actor, project):
        raise BusinessRuleError("Only the delivery manager can complete a project.")
    if project.status != Project.Status.READY:
        raise BusinessRuleError("All milestones must be accepted or cancelled before completion.")
    checklist = (data.get("completion_checklist") or "").strip()
    if not checklist:
        raise BusinessRuleError("Confirm the completion checklist.", fields={"completion_checklist": ["Required"]})
    open_tickets = project.tickets.exclude(status__in=["resolved", "closed"]).count()
    if open_tickets and not (data.get("accept_open_tickets")):
        raise BusinessRuleError(f"{open_tickets} ticket(s) are still open on this project.", code="open_dependencies")
    require_version(project, data.get("version"))
    project.status = Project.Status.COMPLETED
    project.completion_checklist = checklist
    project.completed_at = timezone.now()
    project.bump()
    project.save()
    audit.record(actor.workspace, actor, "project.completed", project, f"Project {project.name} completed")
    return project


def add_project_change(actor, project, data):
    kind = data.get("kind")
    if kind not in ProjectChange.Kind.values:
        raise BusinessRuleError("Choose scope change or defect.", fields={"kind": ["Required"]})
    title = (data.get("title") or "").strip()
    if not title:
        raise BusinessRuleError("Give it a title.", fields={"title": ["Required"]})
    change = ProjectChange.objects.create(
        workspace=actor.workspace, project=project, kind=kind, title=title,
        description=(data.get("description") or "").strip(), raised_by=actor,
    )
    audit.record(actor.workspace, actor, "project.change", change, f"{change.get_kind_display()}: {title}")
    return change


def decide_project_change(actor, change, data):
    if not _is_reviewer(actor, change.project):
        raise BusinessRuleError("Only the delivery manager can decide on this.")
    status = data.get("status")
    if status not in (ProjectChange.Status.APPROVED, ProjectChange.Status.REJECTED, ProjectChange.Status.FIXED):
        raise BusinessRuleError("Choose approved, rejected or fixed.")
    if change.kind == ProjectChange.Kind.SCOPE_CHANGE and status == ProjectChange.Status.FIXED:
        raise BusinessRuleError("Scope changes are approved or rejected, not fixed.")
    if change.kind == ProjectChange.Kind.DEFECT and status == ProjectChange.Status.APPROVED:
        raise BusinessRuleError("Defects are fixed or rejected.")
    change.status = status
    change.decided_by = actor
    change.decision_note = (data.get("note") or "").strip()
    change.save()
    audit.record(actor.workspace, actor, "project.change_decided", change, f"{change.title}: {status}")
    return change
