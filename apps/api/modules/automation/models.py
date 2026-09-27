from django.db import models
from django.db.models import Q

from modules.common.models import TenantModel


class RuleDefinition(TenantModel):
    """A configured copy of an approved rule template (CRM06)."""

    code = models.CharField(max_length=8)
    name = models.CharField(max_length=200)
    trigger = models.TextField()
    conditions = models.TextField()
    action = models.TextField()
    explanation = models.TextField()
    params = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    updated_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["workspace", "code"], name="uniq_rule_code")]


class RuleExecution(TenantModel):
    """One row per business action. The unique key makes retries harmless."""

    rule_code = models.CharField(max_length=8)
    rule_version = models.PositiveIntegerField()
    dedupe_key = models.CharField(max_length=200)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    action_taken = models.CharField(max_length=300)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["workspace", "rule_code", "dedupe_key"], name="uniq_rule_execution")]


class Alert(TenantModel):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"

    rule_code = models.CharField(max_length=8, blank=True)
    recipient = models.ForeignKey("identity.Membership", on_delete=models.CASCADE, related_name="alerts")
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.WARNING)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=300)
    cause = models.TextField(help_text="Why this alert appeared")
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=200)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    resolution_note = models.TextField(blank=True)
    challenge_note = models.TextField(blank=True, help_text="Employee explanation or challenge")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "recipient", "dedupe_key"],
                condition=~Q(status="resolved"),
                name="uniq_unresolved_alert",
            )
        ]


class WorkerHeartbeat(models.Model):
    name = models.CharField(max_length=40, primary_key=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_result = models.JSONField(default=dict, blank=True)
