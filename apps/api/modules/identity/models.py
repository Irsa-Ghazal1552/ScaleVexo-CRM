import secrets
import uuid
from datetime import time

from django.conf import settings
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    OWNER = "owner", "CEO / workspace owner"
    ADMIN = "admin", "Workspace administrator"
    SALES_MANAGER = "sales_manager", "Sales manager"
    SALES_REP = "sales_rep", "Sales representative"
    DELIVERY_MANAGER = "delivery_manager", "Delivery manager"
    DELIVERY_EMPLOYEE = "delivery_employee", "Delivery employee"


PRIVILEGED_ROLES = {Role.OWNER, Role.ADMIN}
SALES_ROLES = {Role.SALES_MANAGER, Role.SALES_REP}
DELIVERY_ROLES = {Role.DELIVERY_MANAGER, Role.DELIVERY_EMPLOYEE}


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    work_start = models.TimeField(default=time(9, 0))
    work_end = models.TimeField(default=time(18, 0))
    work_days = models.CharField(max_length=20, default="0,1,2,3,4", help_text="Python weekday numbers, Monday=0")
    default_currency = models.CharField(max_length=3, default="USD")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    title = models.CharField(max_length=120, blank=True)
    unavailable_until = models.DateField(null=True, blank=True, help_text="Approved leave: no automatic assignment until this date")
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=64, blank=True)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["workspace", "user"], name="uniq_membership")]
        ordering = ["user__first_name", "user__email"]

    def __str__(self):
        return f"{self.display_name} ({self.role})"

    @property
    def display_name(self):
        full = f"{self.user.first_name} {self.user.last_name}".strip()
        return full or self.user.email

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def is_available(self, on_date=None):
        """Eligible for new automatic assignments."""
        if not self.is_active:
            return False
        on_date = on_date or timezone.localdate()
        return not (self.unavailable_until and self.unavailable_until >= on_date)


class Invitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=Role.choices)
    title = models.CharField(max_length=120, blank=True)
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    invited_by = models.ForeignKey(Membership, on_delete=models.SET_NULL, null=True, related_name="+")
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_usable(self):
        return self.accepted_at is None and self.revoked_at is None and self.expires_at > timezone.now()


class AuditEvent(models.Model):
    """Append-only change history. Rows cannot be edited or deleted."""

    id = models.BigAutoField(primary_key=True)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="+")
    actor = models.ForeignKey(Membership, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=64)
    summary = models.CharField(max_length=300)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["workspace", "entity_type", "entity_id"])]

    def save(self, *args, **kwargs):
        if self.pk and not kwargs.get("force_insert"):
            raise PermissionError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events are append-only.")
