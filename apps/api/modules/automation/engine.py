"""Deterministic rule engine (CRM06).

Each rule evaluates the *current* state of the records it watches. That makes
the engine naturally idempotent and self-correcting:

* running it twice produces the same business action once (unique keys);
* alerts whose cause has disappeared (reassigned, rescheduled, closed) are
  resolved automatically, so obsolete follow-ups never fire;
* a paused rule is skipped entirely, so nothing pending executes.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from modules.common.worktime import working_minutes_between, working_minutes_per_day
from modules.identity.models import Membership, Role

from .models import Alert, RuleDefinition, RuleExecution, WorkerHeartbeat

log = logging.getLogger("scalevexo.rules")
MAX_ACTIONS_PER_RULE_RUN = 200


def _active(workspace, role):
    return list(Membership.objects.filter(workspace=workspace, role=role, status="active"))


def _managers_for(member):
    ws = member.workspace
    if member.role in (Role.SALES_REP,):
        people = _active(ws, Role.SALES_MANAGER)
    elif member.role == Role.DELIVERY_EMPLOYEE:
        people = _active(ws, Role.DELIVERY_MANAGER)
    else:
        people = []
    return people or _active(ws, Role.OWNER)


def _recipients_by_role(workspace, role):
    people = _active(workspace, role) if role else []
    return people or _active(workspace, Role.OWNER)


def raise_alert(workspace, rule_code, recipients, entity_type, entity_id, title, cause, dedupe_key, severity="warning"):
    created = 0
    for r in {m.pk: m for m in recipients if m is not None}.values():
        if Alert.objects.filter(workspace=workspace, recipient=r, dedupe_key=dedupe_key).exclude(status="resolved").exists():
            continue
        try:
            with transaction.atomic():
                Alert.objects.create(
                    workspace=workspace, rule_code=rule_code, recipient=r, severity=severity, title=title[:300],
                    cause=cause, entity_type=entity_type, entity_id=str(entity_id), dedupe_key=dedupe_key,
                )
                created += 1
        except IntegrityError:
            pass  # concurrent run created it already
    return created


def resolve_alerts(workspace, dedupe_key, actor=None, note="Condition cleared"):
    return Alert.objects.filter(workspace=workspace, dedupe_key=dedupe_key).exclude(status="resolved").update(
        status="resolved", resolved_at=timezone.now(), resolved_by=actor, resolution_note=note)


def record_execution(workspace, rule_code, dedupe_key, entity_type, entity_id, action):
    """Returns True the first time only."""
    rule = RuleDefinition.objects.filter(workspace=workspace, code=rule_code).first()
    try:
        with transaction.atomic():
            RuleExecution.objects.create(
                workspace=workspace, rule_code=rule_code, rule_version=rule.version if rule else 1,
                dedupe_key=dedupe_key, entity_type=entity_type, entity_id=str(entity_id), action_taken=action,
            )
        return True
    except IntegrityError:
        return False


def _sync(workspace, rule_code, active_keys):
    """Resolve open alerts of this rule whose condition no longer holds."""
    stale = Alert.objects.filter(workspace=workspace, rule_code=rule_code).exclude(status="resolved").exclude(dedupe_key__in=active_keys)
    # Handover alerts (A05) are resolved by the handover workflow itself.
    if rule_code == "A05":
        return 0
    return stale.update(status="resolved", resolved_at=timezone.now(), resolution_note="Condition cleared automatically")


def _auto_owner(member):
    """No automatic assignment to inactive or absent employees."""
    if member is not None and member.is_available():
        return member
    managers = _managers_for(member) if member else []
    return next((m for m in managers if m.is_available()), None)


# ------------------------------------------------------------------ rules
def rule_a01(ws, rule, now):
    from modules.crm.models import Lead

    minutes = int(rule.params.get("working_minutes", 30))
    recipients = _recipients_by_role(ws, rule.params.get("recipient_role", "sales_manager"))
    keys = []
    for lead in Lead.objects.filter(workspace=ws, owner__isnull=True, archived=False).exclude(status="disqualified").select_related("contact")[:MAX_ACTIONS_PER_RULE_RUN]:
        waited = working_minutes_between(ws, lead.created_at, now)
        if waited < minutes:
            continue
        key = f"A01:lead:{lead.pk}"
        keys.append(key)
        raise_alert(ws, "A01", recipients, "lead", lead.pk, f"Unassigned lead: {lead.contact.label}",
                    f"This lead has had no owner for {waited} working minutes (limit {minutes}).", key)
    return _sync(ws, "A01", keys), len(keys)


def rule_a02(ws, rule, now):
    from modules.crm.models import OPEN_STAGES, Opportunity
    from modules.work.models import Task
    from modules.work.services import create_task

    recipients = _recipients_by_role(ws, rule.params.get("recipient_role", "sales_manager"))
    due_hours = int(rule.params.get("task_due_working_hours", 4))
    keys = []
    qs = Opportunity.objects.filter(workspace=ws, stage__in=OPEN_STAGES, archived=False).filter(
        Q(next_action_due__isnull=True) | Q(next_action_due__lte=now)).select_related("owner__user", "owner__workspace")
    for opp in qs[:MAX_ACTIONS_PER_RULE_RUN]:
        key = f"A02:opp:{opp.pk}"
        keys.append(key)
        raise_alert(ws, "A02", recipients, "opportunity", opp.pk, f"No next action: {opp.title}",
                    "This open deal has no next action scheduled in the future.", key)
        owner = _auto_owner(opp.owner)
        has_open = Task.objects.filter(opportunity=opp, status__in=["open", "blocked"], created_by_rule="A02").exists()
        if owner and not has_open:
            episode = f"{key}:{opp.version}"
            if record_execution(ws, "A02", episode, "opportunity", opp.pk, f"Task created for {owner.display_name}"):
                create_task(owner, {
                    "title": f"Set the next action for '{opp.title}'", "kind": "follow_up", "owner_id": owner.pk,
                    "due_at": now + timedelta(hours=due_hours), "opportunity_id": opp.pk,
                    "description": "Created automatically because the deal had no future next action (rule A02).",
                }, check_scope=False, rule_code="A02")
    return _sync(ws, "A02", keys), len(keys)


def rule_a03(ws, rule, now):
    from modules.work.models import Task

    hours = int(rule.params.get("overdue_working_hours", 2))
    esc_days = int(rule.params.get("escalate_after_working_days", 1))
    per_day = working_minutes_per_day(ws)
    keys = []
    qs = Task.objects.filter(workspace=ws, kind="follow_up", status="open", due_at__lt=now).select_related("owner__user", "owner__workspace")
    for task in qs[:MAX_ACTIONS_PER_RULE_RUN]:
        late = working_minutes_between(ws, task.due_at, now)
        if late < hours * 60:
            continue
        key = f"A03:task:{task.pk}:{task.due_at.isoformat()}"
        keys.append(key)
        raise_alert(ws, "A03", [task.owner], "task", task.pk, f"Overdue follow-up: {task.title}",
                    f"Due {task.due_at:%d %b %H:%M} UTC; overdue by {late // 60} working hours.", key)
        if late >= esc_days * per_day:
            esc_key = f"A03:escalate:{task.pk}:{task.due_at.isoformat()}"
            keys.append(esc_key)
            raise_alert(ws, "A03", _managers_for(task.owner), "task", task.pk,
                        f"Escalation: {task.owner.display_name} has an overdue follow-up",
                        f"'{task.title}' has been overdue for more than {esc_days} working day(s).", esc_key, severity="critical")
    return _sync(ws, "A03", keys), len(keys)


def rule_a04(ws, rule, now):
    from modules.crm.models import OPEN_STAGES, Opportunity

    days = int(rule.params.get("quiet_working_days", 3))
    limit = days * working_minutes_per_day(ws)
    keys = []
    for opp in Opportunity.objects.filter(workspace=ws, stage__in=OPEN_STAGES, archived=False).select_related("owner__workspace"):
        last = opp.last_activity_at or opp.created_at
        if working_minutes_between(ws, last, now) < limit:
            continue
        owner = _auto_owner(opp.owner)
        if owner is None:
            continue
        key = f"A04:opp:{opp.pk}:{last.isoformat()}"
        keys.append(key)
        raise_alert(ws, "A04", [owner], "opportunity", opp.pk, f"Update needed: {opp.title}",
                    f"No activity recorded for {days}+ working days. Log what is happening; the deal is not marked lost.", key)
        if len(keys) >= MAX_ACTIONS_PER_RULE_RUN:
            break
    return _sync(ws, "A04", keys), len(keys)


def rule_a06(ws, rule, now):
    from modules.work.models import Milestone

    recipients = _recipients_by_role(ws, rule.params.get("recipient_role", "delivery_manager"))
    today = timezone.localdate()
    keys = []
    qs = Milestone.objects.filter(workspace=ws).exclude(status__in=["accepted", "cancelled"]).exclude(
        project__status="completed").select_related("project")
    for ms in qs[:MAX_ACTIONS_PER_RULE_RUN * 2]:
        reasons = []
        if ms.due_date and ms.due_date < today:
            reasons.append(f"overdue since {ms.due_date:%d %b}")
        blocked = [d.title for d in ms.depends_on.all() if d.status == "blocked"]
        if blocked:
            reasons.append("dependency blocked: " + ", ".join(blocked))
        if ms.status == "blocked":
            reasons.append(f"blocked: {ms.blocker_description}")
        if not reasons:
            continue
        key = f"A06:ms:{ms.pk}"
        keys.append(key)
        extra = [ms.project.manager] if ms.project.manager_id else []
        raise_alert(ws, "A06", recipients + extra, "project", ms.project_id,
                    f"Milestone at risk: {ms.title} ({ms.project.name})", "; ".join(reasons).capitalize() + ".", key)
    return _sync(ws, "A06", keys), len(keys)


def critical_ticket_alert(ticket):
    ws = ticket.workspace
    rule = RuleDefinition.objects.filter(workspace=ws, code="A07").first()
    if rule is None or not rule.enabled:
        return 0
    recipients = []
    incident_owner = rule.params.get("incident_owner_id")
    if incident_owner:
        m = Membership.objects.filter(workspace=ws, pk=incident_owner, status="active").first()
        if m:
            recipients.append(m)
    if ticket.owner_id:
        recipients.append(ticket.owner)
    recipients += _recipients_by_role(ws, rule.params.get("fallback_role", "owner"))
    recipients += _active(ws, Role.DELIVERY_MANAGER)
    key = f"A07:ticket:{ticket.pk}"
    record_execution(ws, "A07", key, "ticket", ticket.pk, "Incident owners notified")
    # raise_alert keeps one unresolved alert per recipient, so repeats are harmless.
    return raise_alert(ws, "A07", recipients, "ticket", ticket.pk, f"CRITICAL ticket #{ticket.number}: {ticket.title}",
                       "A critical client issue was raised and needs an immediate owner.", key, severity="critical")


def rule_a07(ws, rule, now):
    from modules.support.models import Ticket

    keys = []
    for t in Ticket.objects.filter(workspace=ws, severity="critical").exclude(status__in=["resolved", "closed"]).select_related("workspace", "owner"):
        keys.append(f"A07:ticket:{t.pk}")
        critical_ticket_alert(t)
    return _sync(ws, "A07", keys), len(keys)


def rule_a08(ws, rule, now):
    from modules.work.models import Task, TaskReschedule

    count = int(rule.params.get("count", 3))
    window = int(rule.params.get("window_days", 7))
    since = now - timedelta(days=window)
    rows = (TaskReschedule.objects.filter(workspace=ws, created_at__gte=since).values("task").annotate(n=Count("id")).filter(n__gte=count))
    keys = []
    for row in rows:
        task = Task.objects.select_related("owner__workspace", "owner__user").filter(pk=row["task"]).first()
        if task is None or task.status in ("done", "cancelled"):
            continue
        key = f"A08:task:{task.pk}"
        keys.append(key)
        raise_alert(ws, "A08", _managers_for(task.owner), "task", task.pk,
                    f"Repeated rescheduling: {task.title}",
                    f"Rescheduled {row['n']} times in {window} days by/for {task.owner.display_name}. "
                    "Review with the employee - this is not a disciplinary decision.", key, severity="info")
    return _sync(ws, "A08", keys), len(keys)


RULES = {"A01": rule_a01, "A02": rule_a02, "A03": rule_a03, "A04": rule_a04, "A06": rule_a06, "A07": rule_a07, "A08": rule_a08}


def run_rules(workspace, now=None, only=None):
    now = now or timezone.now()
    result = {}
    for rule in RuleDefinition.objects.filter(workspace=workspace).order_by("code"):
        if only and rule.code not in only:
            continue
        fn = RULES.get(rule.code)
        if fn is None:
            continue
        if not rule.enabled:
            result[rule.code] = {"status": "paused"}
            continue
        try:
            resolved, active = fn(workspace, rule, now)
            result[rule.code] = {"status": "ok", "active_conditions": active, "auto_resolved": resolved}
        except Exception as exc:  # one failing rule must not stop the others
            log.exception("Rule %s failed", rule.code)
            result[rule.code] = {"status": "error", "error": str(exc)[:300]}
    return result


def run_all(now=None):
    from modules.identity.models import Workspace

    summary = {}
    for ws in Workspace.objects.all():
        summary[str(ws.pk)] = run_rules(ws, now)
    WorkerHeartbeat.objects.update_or_create(name="rules", defaults={"last_run_at": timezone.now(), "last_result": summary})
    return summary
