"""Revenue and operational reporting (CRM11) and accountability (CRM10).

Every figure is returned with the filter and period that produced it and the
records behind it can be listed, so numbers can always be checked.
Currencies are never added together.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from modules.common import access
from modules.common.errors import BusinessRuleError
from modules.crm.models import OPEN_STAGES, Stage
from modules.identity.models import Role


def period(workspace, params, default_days=90):
    tz = ZoneInfo(workspace.timezone or "UTC")
    today = timezone.now().astimezone(tz).date()
    start = parse_date(params.get("from") or "") or (today - timedelta(days=default_days))
    end = parse_date(params.get("to") or "") or today
    if end < start:
        raise BusinessRuleError("The end date must be after the start date.")
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end, time.max, tzinfo=tz),
        {"from": start.isoformat(), "to": end.isoformat(), "timezone": str(tz)},
    )


def _by_currency(rows, value_field):
    totals = defaultdict(lambda: {"total": Decimal("0"), "count": 0})
    unknown = 0
    for r in rows:
        v = r[value_field]
        if v is None:
            unknown += 1
            continue
        key = r.get("currency") or "?"
        totals[key]["total"] += v
        totals[key]["count"] += 1
    return {"by_currency": {k: {"total": str(v["total"]), "count": v["count"]} for k, v in totals.items()}, "unknown_value_count": unknown}


def neglected_leads_qs(m, days=7):
    cutoff = timezone.now() - timedelta(days=days)
    return access.leads_for(m).exclude(status__in=["disqualified", "qualified"]).filter(
        Q(last_activity_at__lt=cutoff) | Q(last_activity_at__isnull=True, created_at__lt=cutoff))


def overdue_next_action_qs(m):
    return access.opportunities_for(m).filter(stage__in=OPEN_STAGES).filter(
        Q(next_action_due__isnull=True) | Q(next_action_due__lt=timezone.now()))


def overview(m, params):
    from modules.ai.services import usage as ai_usage
    from modules.automation.models import Alert
    from modules.reporting.models import Receipt
    from modules.work.models import Handover, Milestone

    start, end, filters = period(m.workspace, params)
    opps = access.opportunities_for(m)
    commercials = access.can_see_commercials(m)
    data = {"filters": filters, "sections": {}}
    if m.role in (Role.OWNER, Role.SALES_MANAGER):
        open_rows = list(opps.filter(stage__in=OPEN_STAGES).values("value", "currency"))
        won_rows = list(opps.filter(stage=Stage.WON, closed_at__range=(start, end)).values("value", "currency"))
        lost_count = opps.filter(stage=Stage.LOST, closed_at__range=(start, end)).count()
        data["sections"]["pipeline"] = {
            "label": "Open pipeline value (all open deals, not limited by period)",
            "count": len(open_rows), **(_by_currency(open_rows, "value") if commercials else {}),
        }
        data["sections"]["won"] = {
            "label": "Won contract value in period - not cash received",
            "count": len(won_rows), "lost_count": lost_count, **(_by_currency(won_rows, "value") if commercials else {}),
        }
        if m.role == Role.OWNER:
            receipts = list(Receipt.objects.filter(workspace=m.workspace, received_on__range=(start.date(), end.date())).values("amount", "currency"))
            data["sections"]["receipts"] = {"label": "Cash receipts recorded in period (operational register)", "count": len(receipts),
                                            **_by_currency(receipts, "amount")}
        data["sections"]["sales_exceptions"] = {
            "neglected_leads": neglected_leads_qs(m).count(),
            "overdue_next_actions": overdue_next_action_qs(m).count(),
            "unassigned_leads": access.leads_for(m).filter(owner__isnull=True).exclude(status="disqualified").count(),
            "stale_deals_30d": opps.filter(stage__in=OPEN_STAGES, stage_changed_at__lt=timezone.now() - timedelta(days=30)).count(),
        }
    if m.role in (Role.OWNER, Role.DELIVERY_MANAGER):
        tickets = access.tickets_for(m)
        data["sections"]["delivery"] = {
            "handovers_waiting": Handover.objects.filter(workspace=m.workspace, status__in=["pending", "exception", "returned"]).count(),
            "blocked_milestones": Milestone.objects.filter(workspace=m.workspace, status="blocked").count(),
            "overdue_milestones": Milestone.objects.filter(workspace=m.workspace, due_date__lt=timezone.localdate()).exclude(status__in=["accepted", "cancelled"]).count(),
            "open_tickets": tickets.exclude(status__in=["resolved", "closed"]).count(),
            "critical_tickets": tickets.filter(severity="critical").exclude(status__in=["resolved", "closed"]).count(),
            "reopened_tickets_in_period": tickets.filter(reopen_count__gt=0, updated_at__range=(start, end)).count(),
        }
    data["sections"]["alerts"] = {
        "open_for_team": Alert.objects.filter(workspace=m.workspace, recipient__in=access.team_members_visible(m)).exclude(status="resolved").count(),
    }
    if m.role == Role.OWNER:
        data["sections"]["operating_cost"] = {"ai": ai_usage(m.workspace)}
    return data


def report(m, name, params):
    from modules.work.models import Handover, Milestone

    start, end, filters = period(m.workspace, params)
    commercials = access.can_see_commercials(m)
    if name == "neglected-leads":
        days = int(params.get("days") or 7)
        filters["no_activity_days"] = days
        rows = [{"id": str(lead.pk), "type": "lead", "name": lead.contact.label, "status": lead.status,
                 "owner": lead.owner.display_name if lead.owner else None, "last_activity_at": lead.last_activity_at,
                 "created_at": lead.created_at} for lead in neglected_leads_qs(m, days).select_related("contact", "owner__user")]
    elif name == "overdue-next-actions":
        rows = [{"id": str(o.pk), "type": "opportunity", "name": o.title, "customer": o.contact.label, "stage": o.stage,
                 "owner": o.owner.display_name if o.owner else None, "next_action": o.next_action, "next_action_due": o.next_action_due}
                for o in overdue_next_action_qs(m).select_related("contact", "owner__user")]
    elif name == "stage-aging":
        now = timezone.now()
        rows = sorted([
            {"id": str(o.pk), "type": "opportunity", "name": o.title, "stage": o.stage, "days_in_stage": (now - o.stage_changed_at).days,
             "owner": o.owner.display_name if o.owner else None,
             "value": str(o.value) if (commercials and o.value is not None) else None, "currency": o.currency}
            for o in access.opportunities_for(m).filter(stage__in=OPEN_STAGES).select_related("owner__user")
        ], key=lambda r: -r["days_in_stage"])
    elif name == "conversion-by-source":
        filters["basis"] = "Leads created in period, grouped by source"
        leads = access.leads_for(m).filter(created_at__range=(start, end))
        grouped = leads.values("source").annotate(
            total=Count("id", distinct=True),
            qualified=Count("id", filter=Q(status="qualified"), distinct=True),
            disqualified=Count("id", filter=Q(status="disqualified"), distinct=True),
            with_deal=Count("id", filter=Q(opportunities__isnull=False), distinct=True),
            won=Count("id", filter=Q(opportunities__stage="won"), distinct=True),
        ).order_by("-total")
        rows = [{**g, "source": g["source"] or "(no source)",
                 "win_rate_percent": round(100 * g["won"] / g["total"], 1) if g["total"] else 0} for g in grouped]
    elif name == "delivery-blockers":
        rows = []
        for ms in Milestone.objects.filter(workspace=m.workspace, project__in=access.projects_for(m).values("id")).filter(
                Q(status="blocked") | Q(due_date__lt=timezone.localdate())).exclude(status__in=["accepted", "cancelled"]).select_related("project", "owner__user"):
            rows.append({"id": str(ms.project_id), "type": "project", "name": f"{ms.project.name} · {ms.title}", "status": ms.status,
                         "reason": ms.blocker_description or (f"Overdue since {ms.due_date}" if ms.due_date else ""),
                         "owner": ms.owner.display_name if ms.owner else None})
        for h in Handover.objects.filter(workspace=m.workspace, status__in=["pending", "exception", "returned"]).select_related("client", "delivery_owner__user"):
            if m.role not in (Role.OWNER, Role.DELIVERY_MANAGER, Role.SALES_MANAGER):
                continue
            rows.append({"id": str(h.pk), "type": "handover", "name": f"Handover · {h.client.name}", "status": h.status,
                         "reason": h.return_reason or "Awaiting acceptance", "owner": h.delivery_owner.display_name if h.delivery_owner else None})
    elif name == "reopened-tickets":
        rows = [{"id": str(t.pk), "type": "ticket", "name": f"#{t.number} {t.title}", "status": t.status, "reopen_count": t.reopen_count,
                 "client": t.client.name if t.client_id else None, "owner": t.owner.display_name if t.owner else None}
                for t in access.tickets_for(m).filter(reopen_count__gt=0).select_related("client", "owner__user")]
    elif name == "won-deals":
        rows = [{"id": str(o.pk), "type": "opportunity", "name": o.title, "customer": o.contact.label, "closed_at": o.closed_at,
                 "value": str(o.value) if (commercials and o.value is not None) else None, "currency": o.currency,
                 "owner": o.owner.display_name if o.owner else None}
                for o in access.opportunities_for(m).filter(stage="won", closed_at__range=(start, end)).select_related("contact", "owner__user")]
    else:
        raise BusinessRuleError("Unknown report.")
    return {"report": name, "filters": filters, "count": len(rows), "rows": rows}


def accountability(m, params):
    from modules.crm.models import Activity
    from modules.work.models import Task, TaskReschedule

    start, end, filters = period(m.workspace, params, default_days=30)
    now = timezone.now()
    members = access.team_members_visible(m).select_related("user")
    rows = []
    for member in members:
        tasks = Task.objects.filter(workspace=m.workspace, owner=member)
        acts = Activity.objects.filter(workspace=m.workspace, author=member, occurred_at__range=(start, end))
        rows.append({
            "member": {"id": str(member.pk), "name": member.display_name, "role": member.role, "status": member.status},
            "open_tasks": tasks.filter(status__in=["open", "blocked"]).count(),
            "overdue_now": tasks.filter(status="open", due_at__lt=now).count(),
            "missed_deadlines_in_period": tasks.filter(original_due_at__range=(start, end)).filter(
                Q(completed_at__gt=F("original_due_at")) | Q(status="open", original_due_at__lt=now)).count(),
            "completed_in_period": tasks.filter(status="done", completed_at__range=(start, end)).count(),
            "reschedules_in_period": TaskReschedule.objects.filter(workspace=m.workspace, task__owner=member, created_at__range=(start, end)).count(),
            "activities_self_reported": acts.filter(verification="self_reported").count(),
            "activities_provider_confirmed": acts.filter(verification="provider_confirmed").count(),
        })
    return {
        "filters": filters,
        "note": "Counts describe recorded work. They are not a performance score and do not establish misconduct; "
                "review exceptions with the employee and consider workload and role.",
        "rows": rows,
    }


def workspace_export(m):
    """Portable export with stable identifiers and relationships (CRM13)."""
    import json

    from django.apps import apps
    from django.core import serializers as dj_serializers

    from modules.identity.models import Membership

    models = [
        "crm.Contact", "crm.Lead", "crm.Opportunity", "crm.StageHistory", "crm.Activity", "crm.ActivityRevision",
        "work.Client", "work.Handover", "work.ProjectTemplate", "work.Project", "work.Milestone", "work.MilestoneEvent",
        "work.ProjectChange", "work.Task", "work.TaskReschedule", "support.Ticket", "support.TicketNote", "support.TicketEvent",
        "automation.RuleDefinition", "automation.Alert", "reporting.Receipt", "reporting.CorrectionRequest",
        "identity.AuditEvent",
    ]
    out = {
        "format": "scalevexo-crm-export",
        "version": 1,
        "exported_at": timezone.now().isoformat(),
        "workspace": {"id": str(m.workspace.pk), "name": m.workspace.name, "timezone": m.workspace.timezone},
        "members": [{"id": str(x.pk), "email": x.user.email, "name": x.display_name, "role": x.role, "status": x.status}
                    for x in Membership.objects.filter(workspace=m.workspace).select_related("user")],
        "records": {},
    }
    for label in models:
        model = apps.get_model(label)
        qs = model.objects.filter(workspace=m.workspace)
        out["records"][label] = json.loads(dj_serializers.serialize("json", qs))
    return out
