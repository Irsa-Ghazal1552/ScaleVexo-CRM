import uuid

from django.db import models


class TimeStamped(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantModel(TimeStamped):
    """Every business record belongs to exactly one workspace."""

    workspace = models.ForeignKey("identity.Workspace", on_delete=models.CASCADE, related_name="+")

    class Meta:
        abstract = True


class Versioned(models.Model):
    """Optimistic concurrency: clients must send the version they edited."""

    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True

    def bump(self):
        self.version = (self.version or 0) + 1
