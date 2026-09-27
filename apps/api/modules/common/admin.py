"""Django admin for support staff. Business changes should normally go through the app,
because the admin bypasses workflow rules. Audit events are read-only here."""
from django.apps import apps
from django.contrib import admin

from modules.identity.models import AuditEvent


class ReadOnlyAudit(admin.ModelAdmin):
    list_display = ("created_at", "action", "entity_type", "summary", "actor")
    list_filter = ("action", "entity_type")
    search_fields = ("summary", "entity_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(AuditEvent, ReadOnlyAudit)
admin.site.site_header = "ScaleVexo CRM - support admin"

for label in ("identity", "crm", "work", "support", "automation", "reporting", "ai"):
    for model in apps.get_app_config(label).get_models():
        if model is AuditEvent or admin.site.is_registered(model):
            continue
        admin.site.register(model)
