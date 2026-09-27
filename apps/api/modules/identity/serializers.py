from rest_framework import serializers

from .models import AuditEvent, Invitation, Membership, Workspace


class MemberBriefSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="display_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "name", "email", "role", "status", "title"]


class MemberSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="display_name", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    first_name = serializers.CharField(source="user.first_name", read_only=True)
    last_name = serializers.CharField(source="user.last_name", read_only=True)
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)

    class Meta:
        model = Membership
        fields = [
            "id", "name", "email", "first_name", "last_name", "role", "role_label", "status", "title",
            "unavailable_until", "mfa_enabled", "suspended_at", "suspended_reason", "created_at", "last_login",
        ]
        read_only_fields = ["status", "mfa_enabled", "suspended_at", "suspended_reason", "created_at"]


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name", "timezone", "work_start", "work_end", "work_days", "default_currency", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_timezone(self, value):
        from zoneinfo import ZoneInfo

        try:
            ZoneInfo(value)
        except Exception:
            raise serializers.ValidationError("Unknown time zone, e.g. Asia/Karachi or America/New_York.")
        return value

    def validate_work_days(self, value):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts or any(p not in "0123456" or len(p) != 1 for p in parts):
            raise serializers.ValidationError("Use weekday numbers 0-6 separated by commas (Monday = 0).")
        return ",".join(sorted(set(parts)))

    def validate_default_currency(self, value):
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Use a three-letter currency code, e.g. USD.")
        return value


class InvitationSerializer(serializers.ModelSerializer):
    invited_by_name = serializers.CharField(source="invited_by.display_name", read_only=True, default="")
    status = serializers.SerializerMethodField()
    link = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "title", "invited_by_name", "expires_at", "accepted_at", "revoked_at", "created_at", "status", "link"]

    def get_status(self, obj):
        if obj.accepted_at:
            return "accepted"
        if obj.revoked_at:
            return "revoked"
        return "pending" if obj.is_usable else "expired"

    def get_link(self, obj):
        from django.conf import settings

        if obj.accepted_at or obj.revoked_at:
            return ""
        return f"{settings.APP_BASE_URL.rstrip('/')}/accept-invite/{obj.token}"


class AuditEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="System")

    class Meta:
        model = AuditEvent
        fields = ["id", "action", "entity_type", "entity_id", "summary", "data", "actor_name", "created_at"]
