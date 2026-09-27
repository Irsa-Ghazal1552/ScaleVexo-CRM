from rest_framework import serializers

from modules.crm.serializers import _member

from .models import Alert, RuleDefinition, RuleExecution


class AlertSerializer(serializers.ModelSerializer):
    recipient = serializers.SerializerMethodField()
    resolved_by = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = ["id", "rule_code", "severity", "status", "title", "cause", "entity_type", "entity_id", "recipient",
                  "acknowledged_at", "resolved_at", "resolved_by", "resolution_note", "challenge_note", "created_at"]

    def get_recipient(self, obj):
        return _member(obj.recipient)

    def get_resolved_by(self, obj):
        return _member(obj.resolved_by)


class RuleSerializer(serializers.ModelSerializer):
    updated_by = serializers.SerializerMethodField()

    class Meta:
        model = RuleDefinition
        fields = ["id", "code", "name", "trigger", "conditions", "action", "explanation", "params", "enabled", "version", "updated_by", "updated_at"]

    def get_updated_by(self, obj):
        return _member(obj.updated_by)


class RuleExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RuleExecution
        fields = ["id", "rule_code", "rule_version", "dedupe_key", "entity_type", "entity_id", "action_taken", "created_at"]
