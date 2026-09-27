from rest_framework import serializers

from modules.crm.serializers import _member

from .models import Ticket, TicketEvent, TicketNote


class TicketNoteSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = TicketNote
        fields = ["id", "body", "visibility", "author", "created_at"]

    def get_author(self, obj):
        return _member(obj.author)


class TicketEventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = TicketEvent
        fields = ["id", "from_status", "to_status", "note", "snapshot", "actor", "created_at"]

    def get_actor(self, obj):
        return _member(obj.actor)


class TicketSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    waiting_next_owner = serializers.SerializerMethodField()
    client_name = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Ticket
        fields = ["id", "number", "title", "description", "kind", "client_id", "client_name", "project_id", "project_name",
                  "severity", "status", "status_label", "owner", "created_by", "next_action", "waiting_reason",
                  "waiting_next_owner", "waiting_review_at", "resolution_note", "closure_test_result", "resolved_at",
                  "closed_at", "reopen_count", "version", "created_at", "updated_at"]

    def get_owner(self, obj):
        return _member(obj.owner)

    def get_created_by(self, obj):
        return _member(obj.created_by)

    def get_waiting_next_owner(self, obj):
        return _member(obj.waiting_next_owner)

    def get_client_name(self, obj):
        return obj.client.name if obj.client_id else None

    def get_project_name(self, obj):
        return obj.project.name if obj.project_id else None
