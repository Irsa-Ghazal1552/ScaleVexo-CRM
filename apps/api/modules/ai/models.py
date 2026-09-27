from decimal import Decimal

from django.db import models

from modules.common.models import TenantModel


class AISettings(models.Model):
    class Provider(models.TextChoices):
        MOCK = "mock", "Offline test provider (no cost)"
        ANTHROPIC = "anthropic", "Anthropic Claude API"

    workspace = models.OneToOneField("identity.Workspace", on_delete=models.CASCADE, primary_key=True, related_name="ai_settings")
    enabled = models.BooleanField(default=False)
    provider = models.CharField(max_length=16, choices=Provider.choices, default=Provider.MOCK)
    model = models.CharField(max_length=80, default="claude-haiku-4-5")
    monthly_budget_usd = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("5.00"))
    input_cost_per_mtok = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("1.0000"))
    output_cost_per_mtok = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal("5.0000"))
    max_output_tokens = models.PositiveIntegerField(default=600)
    updated_at = models.DateTimeField(auto_now=True)


class AIBudgetMonth(models.Model):
    workspace = models.ForeignKey("identity.Workspace", on_delete=models.CASCADE, related_name="+")
    month = models.CharField(max_length=7)  # YYYY-MM
    spent_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    reserved_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    request_count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "month"], name="uniq_ai_month")]


class AIRequest(TenantModel):
    class Feature(models.TextChoices):
        SUMMARIZE = "summarize", "Summarize notes"
        DRAFT_FOLLOWUP = "draft_followup", "Draft follow-up"

    class Status(models.TextChoices):
        OK = "ok", "Completed"
        DISABLED = "disabled", "AI disabled"
        OVER_BUDGET = "over_budget", "Over budget"
        FAILED = "failed", "Provider failed"

    requested_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    feature = models.CharField(max_length=20, choices=Feature.choices)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    source_activity_ids = models.JSONField(default=list)
    provider = models.CharField(max_length=16)
    model = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    output = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    user_decision = models.CharField(max_length=16, blank=True, help_text="accepted / edited / rejected")

    class Meta:
        ordering = ["-created_at"]
