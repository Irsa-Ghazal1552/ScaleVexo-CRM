from django.utils import timezone
from rest_framework import serializers

from modules.common.access import can_see_commercials
from modules.crm.serializers import ContactSerializer, _member

from .models import Client, Handover, Milestone, MilestoneEvent, Project, ProjectChange, ProjectTemplate, Task, TaskReschedule


class TaskRescheduleSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = TaskReschedule
        fields = ["id", "from_due", "to_due", "reason", "actor", "created_at"]

    def get_actor(self, obj):
        return _member(obj.actor)


class TaskSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    context = serializers.SerializerMethodField()
    reschedules = TaskRescheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = ["id", "title", "description", "kind", "status", "owner", "due_at", "original_due_at", "reschedule_count",
                  "overdue", "outcome", "stop_reason", "blocked_reason", "completed_at", "created_by_rule", "context",
                  "reschedules", "version", "created_at"]

    def get_owner(self, obj):
        return _member(obj.owner)

    def get_overdue(self, obj):
        return obj.status in ("open", "blocked") and obj.due_at < timezone.now()

    def get_context(self, obj):
        """Customer and purpose, so the Today view can be acted on without searching."""
        if obj.opportunity_id:
            o = obj.opportunity
            return {"type": "opportunity", "id": str(o.pk), "label": o.title, "customer": o.contact.label, "stage": o.stage}
        if obj.lead_id:
            l = obj.lead
            return {"type": "lead", "id": str(l.pk), "label": l.contact.label, "customer": l.contact.label, "stage": l.status}
        if obj.ticket_id:
            t = obj.ticket
            return {"type": "ticket", "id": str(t.pk), "label": f"#{t.number} {t.title}", "customer": t.client.name if t.client_id else "Internal"}
        if obj.milestone_id:
            ms = obj.milestone
            return {"type": "project", "id": str(ms.project_id), "label": f"{ms.project.name} · {ms.title}", "customer": ms.project.client.name}
        if obj.project_id:
            p = obj.project
            return {"type": "project", "id": str(p.pk), "label": p.name, "customer": p.client.name}
        if obj.client_id:
            return {"type": "client", "id": str(obj.client_id), "label": obj.client.name, "customer": obj.client.name}
        return None


class ClientSerializer(serializers.ModelSerializer):
    primary_contact = ContactSerializer(read_only=True)
    account_owner = serializers.SerializerMethodField()
    delivery_manager = serializers.SerializerMethodField()
    project_count = serializers.SerializerMethodField()
    open_ticket_count = serializers.SerializerMethodField()

    class Meta:
        model = Client
        fields = ["id", "name", "primary_contact", "account_owner", "delivery_manager", "status", "notes",
                  "project_count", "open_ticket_count", "created_at"]

    def get_account_owner(self, obj):
        return _member(obj.account_owner)

    def get_delivery_manager(self, obj):
        return _member(obj.delivery_manager)

    def get_project_count(self, obj):
        return obj.projects.count()

    def get_open_ticket_count(self, obj):
        return obj.tickets.exclude(status__in=["resolved", "closed"]).count()


class HandoverSerializer(serializers.ModelSerializer):
    delivery_owner = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    opportunity = serializers.SerializerMethodField()
    client_name = serializers.CharField(source="client.name", read_only=True)
    project_id = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Handover
        fields = ["id", "opportunity", "client_id", "client_name", "project_id", "scope", "exclusions", "client_contacts",
                  "commercial_reference", "delivery_owner", "promised_start", "promised_end", "promised_dates_note",
                  "status", "status_label", "return_reason", "decided_by", "decided_at", "created_by", "version", "created_at"]

    def get_delivery_owner(self, obj):
        return _member(obj.delivery_owner)

    def get_decided_by(self, obj):
        return _member(obj.decided_by)

    def get_created_by(self, obj):
        return _member(obj.created_by)

    def get_project_id(self, obj):
        p = getattr(obj, "project", None)
        return str(p.pk) if p else None

    def get_opportunity(self, obj):
        o = obj.opportunity
        m = self.context.get("membership")
        value = str(o.value) if o.value is not None and (m is None or can_see_commercials(m)) else None
        return {"id": str(o.pk), "title": o.title, "service": o.service, "value": value, "currency": o.currency,
                "owner": _member(o.owner), "commercial_decision": o.commercial_decision}


class MilestoneEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = MilestoneEvent
        fields = ["id", "from_status", "to_status", "note", "evidence_snapshot", "actor", "created_at"]

    def get_actor(self, obj):
        return _member(obj.actor)


class MilestoneSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    blocker_next_owner = serializers.SerializerMethodField()
    submitted_by = serializers.SerializerMethodField()
    accepted_by = serializers.SerializerMethodField()
    depends_on = serializers.SerializerMethodField()
    events = MilestoneEventSerializer(many=True, read_only=True)
    overdue = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Milestone
        fields = ["id", "project_id", "title", "description", "order", "owner", "due_date", "overdue", "status", "status_label",
                  "depends_on", "blocker_description", "blocker_next_owner", "evidence", "submitted_by", "submitted_at",
                  "accepted_by", "accepted_at", "override_reason", "cancel_reason", "cancel_impact", "reopen_count",
                  "events", "version"]

    def get_owner(self, obj):
        return _member(obj.owner)

    def get_blocker_next_owner(self, obj):
        return _member(obj.blocker_next_owner)

    def get_submitted_by(self, obj):
        return _member(obj.submitted_by)

    def get_accepted_by(self, obj):
        return _member(obj.accepted_by)

    def get_depends_on(self, obj):
        return [{"id": str(d.pk), "title": d.title, "status": d.status} for d in obj.depends_on.all()]

    def get_overdue(self, obj):
        return bool(obj.due_date and obj.due_date < timezone.localdate() and obj.status not in ("accepted", "cancelled"))


class ProjectChangeSerializer(serializers.ModelSerializer):
    raised_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()

    class Meta:
        model = ProjectChange
        fields = ["id", "kind", "title", "description", "status", "raised_by", "decided_by", "decision_note", "created_at"]

    def get_raised_by(self, obj):
        return _member(obj.raised_by)

    def get_decided_by(self, obj):
        return _member(obj.decided_by)


class ProjectSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    manager = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    progress = serializers.SerializerMethodField()
    handover_id = serializers.UUIDField(read_only=True)
    blocked_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "kind", "client_id", "client_name", "handover_id", "status", "status_label", "manager", "members",
                  "start_date", "due_date", "progress", "blocked_count", "completion_checklist", "completed_at", "version", "created_at"]

    def get_manager(self, obj):
        return _member(obj.manager)

    def get_members(self, obj):
        return [_member(m) for m in obj.members.all()]

    def get_progress(self, obj):
        statuses = [m.status for m in obj.milestones.all()]
        relevant = [s for s in statuses if s != "cancelled"]
        done = len([s for s in relevant if s == "accepted"])
        return {"accepted": done, "total": len(relevant), "percent": round(100 * done / len(relevant)) if relevant else 0}

    def get_blocked_count(self, obj):
        return len([m for m in obj.milestones.all() if m.status == "blocked"])


class ProjectTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectTemplate
        fields = ["id", "name", "description", "milestones", "is_default"]
