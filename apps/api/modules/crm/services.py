import csv
import hashlib
import io
import re
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from modules.common import access, audit
from modules.common.csvsafe import write_csv
from modules.common.errors import BusinessRuleError, require_version
from modules.identity.models import Membership, Role

from .models import (
    Activity,
    ActivityKind,
    ActivityRevision,
    Contact,
    ImportBatch,
    Lead,
    LeadStatus,
    Opportunity,
    Stage,
    StageHistory,
    Verification,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------- contacts
def normalize_email(value):
    value = (value or "").strip().lower()
    return value if EMAIL_RE.match(value) else ""


def normalize_phone(value, country=""):
    """E.164 when the number is valid. The country is never guessed."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        import phonenumbers
    except ImportError:  # pragma: no cover - dependency is in requirements
        digits = re.sub(r"[^\d+]", "", raw)
        return digits if digits.startswith("+") and len(digits) >= 8 else ""
    region = (country or "").upper() or None
    if not raw.startswith("+") and not region:
        return ""
    try:
        parsed = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return ""
    if not phonenumbers.is_valid_number(parsed):
        return ""
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def find_exact_duplicates(workspace, email_n="", phone_n="", exclude_id=None):
    q = Q()
    if email_n:
        q |= Q(email_normalized=email_n)
    if phone_n:
        q |= Q(phone_normalized=phone_n)
    if not q:
        return Contact.objects.none()
    qs = Contact.objects.filter(workspace=workspace, archived=False).filter(q)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs


def similar_contacts(workspace, name="", company="", exclude_id=None):
    """Similar names are suggestions only; never merged automatically."""
    q = Q()
    if name and len(name.strip()) >= 3:
        q |= Q(name__iexact=name.strip())
    if company and len(company.strip()) >= 3:
        q |= Q(company_name__iexact=company.strip())
    if not q:
        return Contact.objects.none()
    qs = Contact.objects.filter(workspace=workspace, archived=False).filter(q)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs[:10]


def _apply_contact_fields(contact, data):
    for f in ("name", "company_name", "title", "email", "phone", "linkedin_url", "website", "country", "notes"):
        if f in data and data[f] is not None:
            setattr(contact, f, str(data[f]).strip())
    contact.email_normalized = normalize_email(contact.email)
    contact.phone_normalized = normalize_phone(contact.phone, contact.country)


def update_contact(actor, contact, data):
    before = {f: getattr(contact, f) for f in ("name", "company_name", "email", "phone")}
    _apply_contact_fields(contact, data)
    if contact.email and not contact.email_normalized:
        raise BusinessRuleError("The email address is not valid.", fields={"email": ["Invalid email"]})
    dupes = find_exact_duplicates(contact.workspace, contact.email_normalized, contact.phone_normalized, exclude_id=contact.pk)
    if dupes.exists():
        raise BusinessRuleError(
            "Another contact already uses this email or phone. Review and merge instead.",
            code="duplicate_contact", fields={"duplicates": [str(d.pk) for d in dupes[:5]]},
        )
    contact.save()
    audit.record(contact.workspace, actor, "contact.updated", contact, f"Updated contact {contact.label}", {"before": before})
    return contact


@transaction.atomic
def merge_contacts(actor, keep, merge, reason):
    """Reviewed merge. Records keep their history and point to the kept contact."""
    from modules.work.models import Client

    if keep.pk == merge.pk:
        raise BusinessRuleError("Choose two different contacts.")
    if not (reason or "").strip():
        raise BusinessRuleError("A reason is required to merge contacts.")
    if Client.objects.filter(primary_contact=merge).exists() and Client.objects.filter(primary_contact=keep).exists():
        raise BusinessRuleError("Both contacts belong to client records; merge the clients first.")
    moved = {
        "leads": Lead.objects.filter(contact=merge).update(contact=keep),
        "opportunities": Opportunity.objects.filter(contact=merge).update(contact=keep),
        "activities": Activity.objects.filter(contact=merge).update(contact=keep),
        "clients": Client.objects.filter(primary_contact=merge).update(primary_contact=keep),
    }
    for f in ("email", "phone", "company_name", "title", "linkedin_url", "website"):
        if not getattr(keep, f) and getattr(merge, f):
            setattr(keep, f, getattr(merge, f))
    keep.notes = (keep.notes + f"\n[Merged from {merge.label} ({merge.pk})]").strip()
    _apply_contact_fields(keep, {})
    keep.save()
    merge.archived = True
    merge.notes = (merge.notes + f"\n[Merged into {keep.pk}]").strip()
    merge.save(update_fields=["archived", "notes", "updated_at"])
    audit.record(keep.workspace, actor, "contact.merged", keep, f"Merged {merge.label} into {keep.label}",
                 {"merged_id": str(merge.pk), "moved": moved, "reason": reason})
    return keep


# ---------------------------------------------------------------- leads
def _eligible_owner(actor, owner_id):
    if not owner_id:
        return None
    owner = Membership.objects.filter(workspace=actor.workspace, pk=owner_id).first()
    if owner is None:
        raise BusinessRuleError("Choose a valid owner.", fields={"owner": ["Unknown member"]})
    if not owner.is_active:
        raise BusinessRuleError("Suspended members cannot own records.", fields={"owner": ["Suspended member"]})
    if owner.role not in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP):
        raise BusinessRuleError("Leads and deals can only be owned by sales team members.", fields={"owner": ["Not in sales"]})
    if actor.role == Role.SALES_REP and owner.pk != actor.pk:
        raise BusinessRuleError("Sales representatives can only assign records to themselves.")
    return owner


def _history(actor, entity_type, entity, from_stage, to_stage, reason=""):
    StageHistory.objects.create(
        workspace=actor.workspace, entity_type=entity_type, entity_id=entity.pk,
        from_stage=from_stage or "", to_stage=to_stage, reason=reason or "", actor=actor,
    )


def _parse_dt(value, workspace):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        dt = parse_datetime(text)
        if dt is None:
            d = parse_date(text)
            if d is None:
                for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M"):
                    try:
                        dt = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
                if dt is None:
                    raise ValueError(f"Unrecognised date: {text}")
            else:
                dt = datetime.combine(d, time(10, 0))
    if timezone.is_naive(dt):
        dt = dt.replace(tzinfo=ZoneInfo(workspace.timezone or "UTC"))
    return dt


def create_lead(actor, data):
    if actor.role not in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP):
        raise BusinessRuleError("Only the sales team can create leads.")
    ws = actor.workspace
    contact_id = data.get("contact_id")
    with transaction.atomic():
        if contact_id:
            contact = Contact.objects.filter(workspace=ws, pk=contact_id, archived=False).first()
            if contact is None:
                raise BusinessRuleError("Contact not found.")
        else:
            name, company = (data.get("name") or "").strip(), (data.get("company_name") or "").strip()
            if not name and not company:
                raise BusinessRuleError("Enter a name or a company.", fields={"name": ["Name or company is required"]})
            contact = Contact(workspace=ws)
            _apply_contact_fields(contact, data)
            if contact.email and not contact.email_normalized:
                raise BusinessRuleError("The email address is not valid.", fields={"email": ["Invalid email"]})
            if not (contact.email or contact.phone or (data.get("source_reference") or "").strip() or contact.linkedin_url):
                raise BusinessRuleError(
                    "Add one contact method (email, phone or LinkedIn) or a source reference.",
                    fields={"email": ["One contact method or source reference is required"]},
                )
            dupes = find_exact_duplicates(ws, contact.email_normalized, contact.phone_normalized)
            if dupes.exists() and not data.get("allow_duplicate_review"):
                d = dupes.first()
                raise BusinessRuleError(
                    f"A contact with this email or phone already exists: {d.label}. Open it or add the lead to it.",
                    code="duplicate_contact", fields={"duplicates": [str(x.pk) for x in dupes[:5]]},
                )
            contact.save()
        owner_id = data.get("owner_id") or (actor.pk if actor.role == Role.SALES_REP else None)
        owner = _eligible_owner(actor, owner_id)
        lead = Lead.objects.create(
            workspace=ws, contact=contact, owner=owner, source=(data.get("source") or "").strip(),
            source_reference=(data.get("source_reference") or "").strip(),
            status=LeadStatus.ASSIGNED if owner else LeadStatus.NEW,
            next_action=(data.get("next_action") or "").strip(),
            next_action_due=_parse_dt(data.get("next_action_due"), ws),
            created_by=actor,
        )
        _history(actor, "lead", lead, "", lead.status, "Created")
        audit.record(ws, actor, "lead.created", lead, f"Created lead {contact.label}")
        if lead.next_action and lead.next_action_due and owner:
            from modules.work.services import create_task

            create_task(actor, {
                "title": lead.next_action, "kind": "follow_up", "owner_id": owner.pk,
                "due_at": lead.next_action_due, "lead_id": lead.pk,
            }, check_scope=False)
    return lead


LEAD_FIELDS = ("source", "source_reference", "need", "fit", "next_action", "next_action_due", "nurture_review_date")


def update_lead(actor, lead, data):
    require_version(lead, data.get("version"))
    changes = {}
    with transaction.atomic():
        locked = Lead.objects.select_for_update().get(pk=lead.pk)
        require_version(locked, data.get("version"))
        for f in LEAD_FIELDS:
            if f in data:
                value = data[f]
                if f == "next_action_due":
                    value = _parse_dt(value, actor.workspace)
                elif f == "nurture_review_date":
                    value = parse_date(value) if value else None
                else:
                    value = (value or "").strip()
                if str(getattr(locked, f)) != str(value):
                    changes[f] = {"from": str(getattr(locked, f)), "to": str(value)}
                    setattr(locked, f, value)
        if "owner_id" in data:
            new_owner = _eligible_owner(actor, data["owner_id"]) if data["owner_id"] else None
            if actor.role == Role.SALES_REP and new_owner is None:
                raise BusinessRuleError("Ask a manager to unassign a lead.")
            if (locked.owner_id or None) != (new_owner.pk if new_owner else None):
                changes["owner"] = {"from": str(locked.owner_id), "to": str(new_owner.pk if new_owner else None)}
                reason = (data.get("reassign_reason") or "").strip()
                if locked.owner_id and not reason:
                    raise BusinessRuleError("A reason is required to reassign an owned lead.", fields={"reassign_reason": ["Required"]})
                locked.owner = new_owner
                if new_owner and locked.status == LeadStatus.NEW:
                    _history(actor, "lead", locked, locked.status, LeadStatus.ASSIGNED, reason or "Owner assigned")
                    locked.status = LeadStatus.ASSIGNED
                    locked.status_changed_at = timezone.now()
                changes["owner"]["reason"] = reason
        if "contact" in data and isinstance(data["contact"], dict):
            update_contact(actor, locked.contact, data["contact"])
        if not changes:
            return locked
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "lead.updated", locked, f"Updated lead {locked.contact.label}", changes)
    return locked


def change_lead_status(actor, lead, to_status, data):
    if to_status not in LeadStatus.values:
        raise BusinessRuleError("Unknown lead status.")
    require_version(lead, data.get("version"))
    with transaction.atomic():
        locked = Lead.objects.select_for_update().get(pk=lead.pk)
        require_version(locked, data.get("version"))
        for f in ("need", "fit", "disqualify_reason"):
            if f in data:
                setattr(locked, f, (data[f] or "").strip())
        if data.get("nurture_review_date"):
            locked.nurture_review_date = parse_date(str(data["nurture_review_date"]))
        errors = {}
        if to_status != LeadStatus.NEW and not locked.owner_id:
            errors["owner"] = ["Assign an owner first"]
        if to_status == LeadStatus.QUALIFIED:
            if not locked.need:
                errors["need"] = ["Record the need"]
            if not locked.fit:
                errors["fit"] = ["Record the fit"]
        if to_status == LeadStatus.NURTURE and not locked.nurture_review_date:
            errors["nurture_review_date"] = ["A review date is required for nurture"]
        if to_status == LeadStatus.DISQUALIFIED and not locked.disqualify_reason:
            errors["disqualify_reason"] = ["A reason is required to disqualify"]
        if errors:
            raise BusinessRuleError("Some information is required for this status.", code="transition_requirements", fields=errors)
        previous = locked.status
        if previous == to_status:
            locked.bump()
            locked.save()
            return locked
        locked.status = to_status
        locked.status_changed_at = timezone.now()
        locked.bump()
        locked.save()
        _history(actor, "lead", locked, previous, to_status, data.get("reason") or locked.disqualify_reason)
        audit.record(actor.workspace, actor, "lead.status", locked, f"Lead {locked.contact.label}: {previous} → {to_status}")
    return locked


# ---------------------------------------------------------------- opportunities
def _money(value):
    if value in (None, ""):
        return None
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise BusinessRuleError("Value must be a number.", fields={"value": ["Invalid number"]})
    if d < 0:
        raise BusinessRuleError("Value cannot be negative.", fields={"value": ["Must be positive"]})
    return d


def _currency(value, required):
    value = (value or "").strip().upper()
    if value and (len(value) != 3 or not value.isalpha()):
        raise BusinessRuleError("Use a three-letter currency code such as USD.", fields={"currency": ["Invalid code"]})
    if required and not value:
        raise BusinessRuleError("Choose the currency for this value.", fields={"currency": ["Required when a value is set"]})
    return value


def create_opportunity(actor, data):
    if actor.role not in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP):
        raise BusinessRuleError("Only the sales team can create deals.")
    ws = actor.workspace
    lead = None
    if data.get("lead_id"):
        lead = access.leads_for(actor).filter(pk=data["lead_id"]).first()
        if lead is None:
            raise BusinessRuleError("Lead not found.")
        contact = lead.contact
    else:
        contact = Contact.objects.filter(workspace=ws, pk=data.get("contact_id"), archived=False).first()
        if contact is None:
            raise BusinessRuleError("Choose a lead or contact for this deal.", fields={"contact_id": ["Required"]})
    title = (data.get("title") or "").strip()
    if not title:
        raise BusinessRuleError("Give the deal a title.", fields={"title": ["Required"]})
    value = _money(data.get("value"))
    currency = _currency(data.get("currency"), value is not None)
    owner = _eligible_owner(actor, data.get("owner_id") or (lead.owner_id if lead and lead.owner_id else actor.pk))
    with transaction.atomic():
        opp = Opportunity.objects.create(
            workspace=ws, contact=contact, lead=lead, title=title, service=(data.get("service") or "").strip(),
            owner=owner, value=value, currency=currency,
            expected_close_date=parse_date(data["expected_close_date"]) if data.get("expected_close_date") else None,
            next_action=(data.get("next_action") or "").strip(),
            next_action_due=_parse_dt(data.get("next_action_due"), ws), created_by=actor,
        )
        _history(actor, "opportunity", opp, "", opp.stage, "Created")
        if lead and lead.status in (LeadStatus.NEW, LeadStatus.ASSIGNED, LeadStatus.CONTACTING):
            prev = lead.status
            lead.need = lead.need or (data.get("need") or "")
            lead.fit = lead.fit or (data.get("fit") or "")
            if lead.need and lead.fit:
                lead.status = LeadStatus.QUALIFIED
                lead.status_changed_at = timezone.now()
                lead.bump()
                lead.save()
                _history(actor, "lead", lead, prev, lead.status, "Deal created")
        audit.record(ws, actor, "opportunity.created", opp, f"Created deal {title}")
        if opp.next_action and opp.next_action_due and owner:
            from modules.work.services import create_task

            create_task(actor, {"title": opp.next_action, "kind": "follow_up", "owner_id": owner.pk,
                                "due_at": opp.next_action_due, "opportunity_id": opp.pk}, check_scope=False)
    return opp


OPP_FIELDS = ("title", "service", "value", "currency", "expected_close_date", "next_action", "next_action_due", "scope_reference")


def update_opportunity(actor, opp, data):
    if not opp.is_open and any(f in data for f in ("value", "currency", "title", "service")):
        raise BusinessRuleError("Closed deals cannot be edited. Reopen the deal first.")
    with transaction.atomic():
        locked = Opportunity.objects.select_for_update().get(pk=opp.pk)
        require_version(locked, data.get("version"))
        changes = {}
        for f in OPP_FIELDS:
            if f not in data:
                continue
            value = data[f]
            if f == "value":
                value = _money(value)
            elif f == "currency":
                value = _currency(value, False)
            elif f == "expected_close_date":
                value = parse_date(value) if value else None
            elif f == "next_action_due":
                value = _parse_dt(value, actor.workspace)
            else:
                value = (value or "").strip()
            if str(getattr(locked, f)) != str(value):
                changes[f] = {"from": str(getattr(locked, f)), "to": str(value)}
                setattr(locked, f, value)
        if locked.value is not None and not locked.currency:
            raise BusinessRuleError("Choose the currency for this value.", fields={"currency": ["Required when a value is set"]})
        if "owner_id" in data and str(data["owner_id"] or "") != str(locked.owner_id or ""):
            owner = _eligible_owner(actor, data["owner_id"])
            reason = (data.get("reassign_reason") or "").strip()
            if locked.owner_id and not reason:
                raise BusinessRuleError("A reason is required to reassign a deal.", fields={"reassign_reason": ["Required"]})
            changes["owner"] = {"from": str(locked.owner_id), "to": str(owner.pk if owner else None), "reason": reason}
            locked.owner = owner
        if "title" in data and not locked.title:
            raise BusinessRuleError("Give the deal a title.", fields={"title": ["Required"]})
        if not changes:
            return locked
        locked.bump()
        locked.save()
        audit.record(actor.workspace, actor, "opportunity.updated", locked, f"Updated deal {locked.title}", changes)
    return locked


def move_stage(actor, opp, to_stage, data):
    """Stage movement with validation (CRM03). Won is handled by work.services.win_opportunity."""
    if to_stage not in Stage.values:
        raise BusinessRuleError("Unknown stage.")
    if to_stage == Stage.WON:
        from modules.work.services import win_opportunity

        return win_opportunity(actor, opp, data)
    with transaction.atomic():
        locked = Opportunity.objects.select_for_update().get(pk=opp.pk)
        require_version(locked, data.get("version"))
        previous = locked.stage
        if previous == Stage.WON:
            raise BusinessRuleError("A won deal cannot change stage. Record a new deal or a scope change instead.")
        if previous == to_stage:
            return locked
        if "scope_reference" in data:
            locked.scope_reference = (data.get("scope_reference") or "").strip()
        reason = (data.get("reason") or "").strip()
        errors = {}
        if to_stage == Stage.PROPOSAL and not locked.scope_reference:
            errors["scope_reference"] = ["A scope reference is required for a proposal"]
        if to_stage == Stage.NEGOTIATION and not locked.scope_reference:
            errors["scope_reference"] = ["A scope reference is required before negotiation"]
        if to_stage == Stage.LOST:
            reason = reason or (data.get("lost_reason") or "").strip()
            if not reason:
                errors["lost_reason"] = ["A reason is required to close a deal as lost"]
            locked.lost_reason = reason
            locked.closed_at = timezone.now()
        if previous == Stage.LOST and to_stage != Stage.LOST:
            if not reason:
                errors["reason"] = ["A reason is required to reopen a lost deal"]
            locked.closed_at = None
        if errors:
            raise BusinessRuleError("Some information is required for this stage.", code="transition_requirements", fields=errors)
        locked.stage = to_stage
        locked.stage_changed_at = timezone.now()
        locked.bump()
        locked.save()
        _history(actor, "opportunity", locked, previous, to_stage, reason)
        audit.record(actor.workspace, actor, "opportunity.stage", locked, f"Deal {locked.title}: {previous} → {to_stage}", {"reason": reason})
        if to_stage == Stage.LOST:
            from modules.work.models import Task

            Task.objects.filter(opportunity=locked, status__in=["open", "blocked"]).update(
                status="cancelled", stop_reason="Deal closed as lost", completed_at=timezone.now()
            )
    return locked


def pipeline_summary(opps):
    """Totals per stage and currency. Currencies are never combined (CRM03)."""
    now = timezone.now()
    stages = {}
    for s in Stage.values:
        stages[s] = {"stage": s, "count": 0, "unknown_value_count": 0, "totals": {}}
    for o in opps:
        bucket = stages[o.stage]
        bucket["count"] += 1
        if o.value is None:
            bucket["unknown_value_count"] += 1
        else:
            key = o.currency or "?"
            bucket["totals"][key] = str(Decimal(bucket["totals"].get(key, "0")) + o.value)
    return {"stages": list(stages.values()), "generated_at": now.isoformat()}


# ---------------------------------------------------------------- activities
def log_activity(actor, data):

    ws = actor.workspace
    kind = data.get("kind")
    if kind not in ActivityKind.values:
        raise BusinessRuleError("Choose the activity type.", fields={"kind": ["Required"]})
    lead = opp = client = contact = None
    if data.get("lead_id"):
        lead = access.leads_for(actor).filter(pk=data["lead_id"]).first()
        if lead is None:
            raise BusinessRuleError("Lead not found.")
        contact = lead.contact
    if data.get("opportunity_id"):
        opp = access.opportunities_for(actor).filter(pk=data["opportunity_id"]).first()
        if opp is None:
            raise BusinessRuleError("Deal not found.")
        contact = opp.contact
        lead = lead or opp.lead
    if data.get("client_id"):
        client = access.clients_for(actor).filter(pk=data["client_id"]).first()
        if client is None:
            raise BusinessRuleError("Client not found.")
        contact = contact or client.primary_contact
    if data.get("contact_id") and not contact:
        contact = Contact.objects.filter(workspace=ws, pk=data["contact_id"]).first()
    if not (lead or opp or client):
        raise BusinessRuleError("Link the activity to a lead, deal or client.")
    outcome = (data.get("outcome") or "").strip()
    body = (data.get("body") or "").strip()
    if kind != ActivityKind.NOTE and not outcome:
        raise BusinessRuleError("Record the outcome.", fields={"outcome": ["Required"]})
    if kind == ActivityKind.NOTE and not body:
        raise BusinessRuleError("Write the note.", fields={"body": ["Required"]})
    occurred_at = _parse_dt(data.get("occurred_at"), ws) or timezone.now()
    if occurred_at > timezone.now() + timedelta(minutes=5):
        raise BusinessRuleError("An activity cannot be recorded in the future. Create a follow-up instead.",
                                fields={"occurred_at": ["In the future"]})
    with transaction.atomic():
        activity = Activity.objects.create(
            workspace=ws, kind=kind, contact=contact, lead=lead, opportunity=opp, client=client,
            subject=(data.get("subject") or "").strip(), outcome=outcome, body=body, occurred_at=occurred_at,
            author=actor,
            # Release 1 has no connected providers: manual entries are always self-reported (CRM04).
            verification=Verification.SELF_REPORTED,
            source_url=(data.get("source_url") or "").strip(),
            next_action=(data.get("next_action") or "").strip(),
        )
        meaningful = kind != ActivityKind.NOTE or len(body) > 0
        if meaningful:
            if lead:
                Lead.objects.filter(pk=lead.pk).update(last_activity_at=max(occurred_at, lead.last_activity_at or occurred_at))
                if lead.status in (LeadStatus.NEW, LeadStatus.ASSIGNED) and kind != ActivityKind.NOTE and lead.owner_id:
                    Lead.objects.filter(pk=lead.pk).update(status=LeadStatus.CONTACTING, status_changed_at=timezone.now(), version=lead.version + 1)
                    _history(actor, "lead", lead, lead.status, LeadStatus.CONTACTING, "First contact recorded")
            if opp:
                Opportunity.objects.filter(pk=opp.pk).update(last_activity_at=max(occurred_at, opp.last_activity_at or occurred_at))
        next_due = data.get("next_action_due")
        if activity.next_action and next_due:
            from modules.work.services import create_task

            due = _parse_dt(next_due, ws)
            create_task(actor, {
                "title": activity.next_action, "kind": "follow_up", "owner_id": actor.pk, "due_at": due,
                "lead_id": lead.pk if lead else None, "opportunity_id": opp.pk if opp else None,
                "client_id": client.pk if client else None,
            }, check_scope=False)
            target = opp or lead
            if target is not None:
                type(target).objects.filter(pk=target.pk).update(next_action=activity.next_action, next_action_due=due)
        audit.record(ws, actor, "activity.created", activity, f"Logged {kind}: {activity.subject or outcome or body[:60]}")
    return activity


def edit_activity(actor, activity, data):
    if activity.author_id != actor.pk and actor.role not in (Role.OWNER, Role.SALES_MANAGER):
        raise BusinessRuleError("Only the author or a manager can correct this activity.")
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BusinessRuleError("Explain the correction.", fields={"reason": ["Required"]})
    editable = ("subject", "outcome", "body", "next_action")
    previous = {f: getattr(activity, f) for f in editable}
    previous["occurred_at"] = activity.occurred_at.isoformat()
    changed = False
    for f in editable:
        if f in data and (data[f] or "") != getattr(activity, f):
            setattr(activity, f, (data[f] or "").strip())
            changed = True
    if "occurred_at" in data and data["occurred_at"]:
        # Only managers may change when something happened; employees request a correction.
        new_time = _parse_dt(data["occurred_at"], actor.workspace)
        if new_time != activity.occurred_at:
            if actor.role not in (Role.OWNER, Role.SALES_MANAGER):
                raise BusinessRuleError("Historical times cannot be rewritten. Submit a correction request instead.", code="timestamp_locked")
            activity.occurred_at = new_time
            changed = True
    if not changed:
        return activity
    with transaction.atomic():
        ActivityRevision.objects.create(workspace=actor.workspace, activity=activity, editor=actor, previous=previous, reason=reason)
        activity.corrected = True
        activity.save()
        audit.record(actor.workspace, actor, "activity.corrected", activity, "Corrected activity", {"reason": reason, "previous": previous})
    return activity


# ---------------------------------------------------------------- CSV import (CRM02)
IMPORT_TARGETS = [
    "name", "first_name", "last_name", "company_name", "title", "email", "phone", "country", "linkedin_url", "website",
    "source", "source_reference", "owner", "status", "next_action", "next_action_due", "notes",
]

HEADER_HINTS = {
    "name": ["name", "full name", "contact", "contact name", "lead name"],
    "first_name": ["first name", "firstname", "first"],
    "last_name": ["last name", "lastname", "surname", "last"],
    "company_name": ["company", "company name", "organisation", "organization", "business", "account"],
    "title": ["title", "job title", "designation", "position", "role"],
    "email": ["email", "e-mail", "email address", "mail"],
    "phone": ["phone", "phone number", "mobile", "cell", "contact number", "whatsapp"],
    "country": ["country", "country code"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin profile"],
    "website": ["website", "url", "site", "domain"],
    "source": ["source", "lead source", "channel"],
    "source_reference": ["source reference", "reference", "source url"],
    "owner": ["owner", "assigned to", "sales rep", "rep", "assignee"],
    "status": ["status", "lead status", "stage"],
    "next_action": ["next action", "next step", "follow up", "follow-up"],
    "next_action_due": ["next action date", "follow up date", "follow-up date", "due", "due date", "next action due"],
    "notes": ["notes", "note", "comments", "remarks", "description"],
}

STATUS_ALIASES = {
    "new": LeadStatus.NEW, "assigned": LeadStatus.ASSIGNED, "contacting": LeadStatus.CONTACTING,
    "contacted": LeadStatus.CONTACTING, "in progress": LeadStatus.CONTACTING, "qualified": LeadStatus.QUALIFIED,
    "nurture": LeadStatus.NURTURE, "cold": LeadStatus.NURTURE, "disqualified": LeadStatus.DISQUALIFIED,
    "lost": LeadStatus.DISQUALIFIED, "not interested": LeadStatus.DISQUALIFIED,
}


def _decode(content):
    if isinstance(content, str):
        return content
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise BusinessRuleError("The file could not be read as text.")


def _read_rows(text):
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise BusinessRuleError("The file is empty.")
    headers = [h.strip() for h in rows[0]]
    if not any(headers):
        raise BusinessRuleError("The first row must contain column names.")
    return headers, rows[1:]


def suggest_mapping(headers):
    mapping = {}
    used = set()
    for h in headers:
        key = h.strip().lower().replace("_", " ")
        for target, hints in HEADER_HINTS.items():
            if target in used:
                continue
            if key in hints:
                mapping[h] = target
                used.add(target)
                break
    return mapping


def import_preview(actor, file_name, content):
    if actor.role not in (Role.OWNER, Role.SALES_MANAGER):
        raise BusinessRuleError("Only a sales manager or the owner can import leads.")
    text = _decode(content)
    if len(text) > 10 * 1024 * 1024:
        raise BusinessRuleError("The file is larger than 10 MB. Split it into smaller files.")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = ImportBatch.objects.filter(workspace=actor.workspace, sha256=digest).first()
    if existing:
        return existing, True
    headers, rows = _read_rows(text)
    batch = ImportBatch.objects.create(
        workspace=actor.workspace, file_name=file_name[:255], sha256=digest, raw_csv=text, headers=headers,
        row_count=len(rows), mapping=suggest_mapping(headers), created_by=actor,
    )
    audit.record(actor.workspace, actor, "import.previewed", batch, f"Uploaded {file_name} ({len(rows)} rows)")
    return batch, False


def preview_rows(batch, limit=20):
    headers, rows = _read_rows(batch.raw_csv)
    return [dict(zip(headers, r, strict=False)) for r in rows[:limit]]


def _owner_lookup(workspace):
    lookup = {}
    for m in Membership.objects.filter(workspace=workspace, status="active").select_related("user"):
        if m.role not in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP):
            continue
        lookup[m.user.email.lower()] = m
        lookup[m.display_name.lower()] = m
        if m.user.first_name:
            lookup.setdefault(m.user.first_name.lower(), m)
    return lookup


def import_confirm(actor, batch, mapping, default_owner_id=None):
    if actor.role not in (Role.OWNER, Role.SALES_MANAGER):
        raise BusinessRuleError("Only a sales manager or the owner can import leads.")
    with transaction.atomic():
        batch = ImportBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status == ImportBatch.Status.CONFIRMED:
            return batch  # retry creates nothing new
        invalid_targets = [t for t in (mapping or {}).values() if t and t not in IMPORT_TARGETS]
        if invalid_targets:
            raise BusinessRuleError(f"Unknown target fields: {', '.join(invalid_targets)}")
        mapped = set(t for t in mapping.values() if t)
        if not ({"name", "first_name", "company_name"} & mapped):
            raise BusinessRuleError("Map at least one of: name, first name or company.")
        default_owner = None
        if default_owner_id:
            default_owner = _eligible_owner(actor, default_owner_id)
        headers, rows = _read_rows(batch.raw_csv)
        owners = _owner_lookup(actor.workspace)
        ws = actor.workspace
        seen_emails, seen_phones = {}, {}
        counts = {"total_rows": len(rows), "created": 0, "duplicates": 0, "invalid": 0, "skipped_blank": 0}
        error_rows = []
        for index, raw in enumerate(rows, start=2):  # spreadsheet row numbers (header is row 1)
            values = dict(zip(headers, raw + [""] * (len(headers) - len(raw)), strict=False))
            if not any((v or "").strip() for v in values.values()):
                counts["skipped_blank"] += 1
                continue
            row = {}
            for header, target in mapping.items():
                if target:
                    row[target] = (values.get(header) or "").strip()
            name = row.get("name") or " ".join(x for x in (row.get("first_name"), row.get("last_name")) if x).strip()
            company = row.get("company_name", "")
            problems = []
            if not name and not company:
                problems.append("Name or company is required")
            email_n = normalize_email(row.get("email"))
            if row.get("email") and not email_n:
                problems.append("Invalid email address")
            phone_n = normalize_phone(row.get("phone"), row.get("country"))
            if not (row.get("email") or row.get("phone") or row.get("source_reference") or row.get("linkedin_url") or row.get("source")):
                problems.append("No contact method or source reference")
            owner = None
            if row.get("owner"):
                owner = owners.get(row["owner"].lower())
                if owner is None:
                    problems.append(f"Owner '{row['owner']}' is not an active sales member")
            owner = owner or default_owner
            status = LeadStatus.ASSIGNED if owner else LeadStatus.NEW
            if row.get("status"):
                mapped_status = STATUS_ALIASES.get(row["status"].lower())
                if mapped_status is None:
                    problems.append(f"Unknown status '{row['status']}'")
                else:
                    status = mapped_status
                    if status != LeadStatus.NEW and not owner:
                        status = LeadStatus.NEW
            due = None
            if row.get("next_action_due"):
                try:
                    due = _parse_dt(row["next_action_due"], ws)
                except ValueError:
                    problems.append(f"Unrecognised date '{row['next_action_due']}'")
            if problems:
                counts["invalid"] += 1
                error_rows.append([index, "invalid", "; ".join(problems)] + raw)
                continue
            dup_reason = None
            if email_n and email_n in seen_emails:
                dup_reason = f"Same email as row {seen_emails[email_n]}"
            elif phone_n and phone_n in seen_phones:
                dup_reason = f"Same phone as row {seen_phones[phone_n]}"
            else:
                existing = find_exact_duplicates(ws, email_n, phone_n).first()
                if existing:
                    dup_reason = f"Matches existing contact {existing.label}"
            if dup_reason:
                counts["duplicates"] += 1
                error_rows.append([index, "duplicate", dup_reason] + raw)
                continue
            if email_n:
                seen_emails[email_n] = index
            if phone_n:
                seen_phones[phone_n] = index
            contact = Contact(workspace=ws, name=name, company_name=company)
            _apply_contact_fields(contact, {k: row.get(k) for k in ("title", "email", "phone", "country", "linkedin_url", "website", "notes") if row.get(k)})
            contact.save()
            try:
                with transaction.atomic():
                    Lead.objects.create(
                        workspace=ws, contact=contact, owner=owner, status=status, source=row.get("source", ""),
                        source_reference=row.get("source_reference", ""), next_action=row.get("next_action", ""),
                        next_action_due=due, created_by=actor, import_batch=batch, import_row=index,
                    )
            except IntegrityError:
                counts["duplicates"] += 1
                error_rows.append([index, "duplicate", "Row already imported"] + raw)
                continue
            counts["created"] += 1
        batch.status = ImportBatch.Status.CONFIRMED
        batch.mapping = mapping
        batch.default_owner = default_owner
        batch.counts = counts
        batch.errors_csv = write_csv(["row", "result", "reason"] + headers, error_rows) if error_rows else ""
        batch.confirmed_at = timezone.now()
        batch.save()
        audit.record(ws, actor, "import.confirmed", batch, f"Imported {batch.file_name}", counts)
    return batch


def export_leads_csv(actor):
    qs = access.leads_for(actor).select_related("contact", "owner__user")
    header = ["lead_id", "name", "company", "email", "phone", "source", "status", "owner", "next_action", "next_action_due", "created_at"]
    rows = [
        [lead.pk, lead.contact.name, lead.contact.company_name, lead.contact.email, lead.contact.phone, lead.source, lead.status,
         lead.owner.display_name if lead.owner else "", lead.next_action, lead.next_action_due.isoformat() if lead.next_action_due else "",
         lead.created_at.isoformat()]
        for lead in qs
    ]
    return write_csv(header, rows)
