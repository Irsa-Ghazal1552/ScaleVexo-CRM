from django.utils import timezone
from rest_framework import serializers

from modules.common.access import can_see_commercials

from .models import Activity, ActivityRevision, Contact, ImportBatch, Lead, Opportunity, StageHistory


def _member(m):
    if m is None:
        return None
    return {"id": str(m.pk), "name": m.display_name, "role": m.role}


class ContactSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = ["id", "label", "name", "company_name", "title", "email", "phone", "phone_normalized", "linkedin_url",
                  "website", "country", "notes", "archived", "created_at"]


class LeadSerializer(serializers.ModelSerializer):
    contact = ContactSerializer(read_only=True)
    owner = serializers.SerializerMethodField()
    shared_with = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    days_in_status = serializers.SerializerMethodField()
    next_action_overdue = serializers.SerializerMethodField()
    opportunity_count = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = ["id", "contact", "owner", "shared_with", "source", "source_reference", "status", "status_label",
                  "status_changed_at", "days_in_status", "need", "fit", "nurture_review_date", "disqualify_reason",
                  "next_action", "next_action_due", "next_action_overdue", "last_activity_at", "opportunity_count",
                  "version", "created_at", "updated_at"]

    def get_owner(self, obj):
        return _member(obj.owner)

    def get_shared_with(self, obj):
        return [_member(m) for m in obj.shared_with.all()]

    def get_days_in_status(self, obj):
        return (timezone.now() - obj.status_changed_at).days

    def get_next_action_overdue(self, obj):
        return bool(obj.next_action_due and obj.next_action_due < timezone.now())

    def get_opportunity_count(self, obj):
        return obj.opportunities.count()


class OpportunitySerializer(serializers.ModelSerializer):
    contact = ContactSerializer(read_only=True)
    owner = serializers.SerializerMethodField()
    stage_label = serializers.CharField(source="get_stage_display", read_only=True)
    days_in_stage = serializers.SerializerMethodField()
    next_action_overdue = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField()
    lead_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Opportunity
        fields = ["id", "title", "service", "contact", "lead_id", "owner", "stage", "stage_label", "stage_changed_at",
                  "days_in_stage", "value", "currency", "expected_close_date", "next_action", "next_action_due",
                  "next_action_overdue", "scope_reference", "lost_reason", "commercial_decision", "closed_at",
                  "last_activity_at", "handover", "version", "created_at", "updated_at"]

    def _m(self):
        return self.context.get("membership")

    def get_owner(self, obj):
        return _member(obj.owner)

    def get_days_in_stage(self, obj):
        return (timezone.now() - obj.stage_changed_at).days

    def get_next_action_overdue(self, obj):
        return obj.is_open and (obj.next_action_due is None or obj.next_action_due < timezone.now())

    def get_value(self, obj):
        m = self._m()
        if obj.value is None or (m is not None and not can_see_commercials(m)):
            return None
        return str(obj.value)

    def get_handover(self, obj):
        h = getattr(obj, "handover", None)
        if h is None:
            return None
        project = getattr(h, "project", None)
        return {"id": str(h.pk), "status": h.status, "client_id": str(h.client_id), "project_id": str(project.pk) if project else None}


class StageHistorySerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = StageHistory
        fields = ["id", "from_stage", "to_stage", "reason", "actor", "created_at"]

    def get_actor(self, obj):
        return _member(obj.actor)


class ActivityRevisionSerializer(serializers.ModelSerializer):
    editor = serializers.SerializerMethodField()

    class Meta:
        model = ActivityRevision
        fields = ["id", "previous", "reason", "editor", "created_at"]

    def get_editor(self, obj):
        return _member(obj.editor)


class ActivitySerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    verification_label = serializers.CharField(source="get_verification_display", read_only=True)
    recorded_at = serializers.DateTimeField(read_only=True)
    revisions = ActivityRevisionSerializer(many=True, read_only=True)
    links = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = ["id", "kind", "kind_label", "subject", "outcome", "body", "occurred_at", "recorded_at", "author",
                  "verification", "verification_label", "provider_reference", "source_url", "next_action", "corrected",
                  "revisions", "links", "lead_id", "opportunity_id", "client_id", "contact_id"]

    def get_author(self, obj):
        return _member(obj.author)

    def get_links(self, obj):
        out = {}
        if obj.opportunity_id:
            out["opportunity"] = obj.opportunity.title
        if obj.lead_id:
            out["lead"] = obj.lead.contact.label
        if obj.client_id:
            out["client"] = obj.client.name
        return out


class ImportBatchSerializer(serializers.ModelSerializer):
    created_by = serializers.SerializerMethodField()
    has_errors = serializers.SerializerMethodField()

    class Meta:
        model = ImportBatch
        fields = ["id", "file_name", "status", "headers", "row_count", "mapping", "counts", "created_by", "created_at",
                  "confirmed_at", "has_errors"]

    def get_created_by(self, obj):
        return _member(obj.created_by)

    def get_has_errors(self, obj):
        return bool(obj.errors_csv)
