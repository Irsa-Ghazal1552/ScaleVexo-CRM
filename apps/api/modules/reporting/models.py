from django.db import models

from modules.common.models import TenantModel


class Receipt(TenantModel):
    """Manually recorded cash receipt. An operational register, not a ledger (CRM11)."""

    client = models.ForeignKey("work.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts")
    opportunity = models.ForeignKey("crm.Opportunity", on_delete=models.SET_NULL, null=True, blank=True, related_name="receipts")
    received_on = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    evidence_reference = models.CharField(max_length=300)
    note = models.TextField(blank=True)
    recorded_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-received_on", "-created_at"]


class CorrectionRequest(TenantModel):
    """An employee asks for a correction to their own history (CRM10)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    requested_by = models.ForeignKey("identity.Membership", on_delete=models.CASCADE, related_name="correction_requests")
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    field = models.CharField(max_length=60, blank=True)
    current_value = models.TextField(blank=True)
    requested_value = models.TextField(blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    reviewed_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    review_note = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
