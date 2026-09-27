from rest_framework import serializers

from modules.crm.serializers import _member

from .models import CorrectionRequest, Receipt


class ReceiptSerializer(serializers.ModelSerializer):
    recorded_by = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    opportunity_title = serializers.SerializerMethodField()

    class Meta:
        model = Receipt
        fields = ["id", "client_id", "client_name", "opportunity_id", "opportunity_title", "received_on", "amount", "currency",
                  "evidence_reference", "note", "recorded_by", "created_at"]

    def get_recorded_by(self, obj):
        return _member(obj.recorded_by)

    def get_client_name(self, obj):
        return obj.client.name if obj.client_id else None

    def get_opportunity_title(self, obj):
        return obj.opportunity.title if obj.opportunity_id else None


class CorrectionRequestSerializer(serializers.ModelSerializer):
    requested_by = serializers.SerializerMethodField()
    reviewed_by = serializers.SerializerMethodField()

    class Meta:
        model = CorrectionRequest
        fields = ["id", "requested_by", "entity_type", "entity_id", "field", "current_value", "requested_value", "reason",
                  "status", "reviewed_by", "review_note", "reviewed_at", "created_at"]

    def get_requested_by(self, obj):
        return _member(obj.requested_by)

    def get_reviewed_by(self, obj):
        return _member(obj.reviewed_by)
