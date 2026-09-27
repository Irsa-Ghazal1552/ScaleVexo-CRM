from django.db import models

from modules.common.models import TenantModel, Versioned


class Ticket(TenantModel, Versioned):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        NEW = "new", "New"
        TRIAGED = "triaged", "Triaged"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING_CUSTOMER = "waiting_customer", "Waiting on customer"
        WAITING_INTERNAL = "waiting_internal", "Waiting internal"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=16, default="client", choices=[("client", "Client request"), ("internal", "Internal issue")])
    client = models.ForeignKey("work.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    project = models.ForeignKey("work.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="tickets")
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_tickets")
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    next_action = models.CharField(max_length=300, blank=True)
    waiting_reason = models.TextField(blank=True)
    waiting_next_owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    waiting_review_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    closure_test_result = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reopen_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["workspace", "number"], name="uniq_ticket_number")]


class TicketNote(TenantModel):
    class Visibility(models.TextChoices):
        INTERNAL = "internal", "Internal note"
        CLIENT = "client", "Client-visible"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField()
    visibility = models.CharField(max_length=16, choices=Visibility.choices, default=Visibility.INTERNAL)

    class Meta:
        ordering = ["created_at"]


class TicketEvent(TenantModel):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    note = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
