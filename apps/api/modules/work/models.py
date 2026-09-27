from django.db import models

from modules.common.models import TenantModel, Versioned


class Task(TenantModel, Versioned):
    class Kind(models.TextChoices):
        FOLLOW_UP = "follow_up", "Follow-up"
        TASK = "task", "Task"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"
        CANCELLED = "cancelled", "Cancelled"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TASK)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    owner = models.ForeignKey("identity.Membership", on_delete=models.PROTECT, related_name="tasks")
    due_at = models.DateTimeField()
    original_due_at = models.DateTimeField()
    reschedule_count = models.PositiveIntegerField(default=0)
    outcome = models.TextField(blank=True)
    stop_reason = models.TextField(blank=True)
    blocked_reason = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lead = models.ForeignKey("crm.Lead", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    opportunity = models.ForeignKey("crm.Opportunity", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    client = models.ForeignKey("work.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    project = models.ForeignKey("work.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    milestone = models.ForeignKey("work.Milestone", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    ticket = models.ForeignKey("support.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    created_by_rule = models.CharField(max_length=8, blank=True)

    class Meta:
        ordering = ["due_at"]
        indexes = [models.Index(fields=["workspace", "owner", "status", "due_at"])]


class TaskReschedule(TenantModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reschedules")
    from_due = models.DateTimeField()
    to_due = models.DateTimeField()
    reason = models.TextField()
    actor = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class Client(TenantModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    name = models.CharField(max_length=200)
    primary_contact = models.ForeignKey("crm.Contact", on_delete=models.PROTECT, related_name="clients")
    account_owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    delivery_manager = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["workspace", "primary_contact"], name="uniq_client_contact")]


class Handover(TenantModel, Versioned):
    """Sales to delivery handover created when a deal is won (CRM07)."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending acceptance"
        ACCEPTED = "accepted", "Accepted"
        RETURNED = "returned", "Returned to sales"
        EXCEPTION = "exception", "Exception - needs owner"

    opportunity = models.OneToOneField("crm.Opportunity", on_delete=models.PROTECT, related_name="handover")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="handovers")
    scope = models.TextField()
    exclusions = models.TextField(blank=True)
    client_contacts = models.TextField(blank=True)
    commercial_reference = models.CharField(max_length=300)
    delivery_owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    promised_start = models.DateField(null=True, blank=True)
    promised_end = models.DateField(null=True, blank=True)
    promised_dates_note = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    return_reason = models.TextField(blank=True)
    decided_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class ProjectTemplate(TenantModel):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    milestones = models.JSONField(default=list, help_text='[{"title": "...", "offset_days": 7, "depends_on": [0]}]')
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]


class Project(TenantModel, Versioned):
    class Kind(models.TextChoices):
        ONBOARDING = "onboarding", "Onboarding"
        DELIVERY = "delivery", "Delivery"

    class Status(models.TextChoices):
        PENDING_HANDOVER = "pending_handover", "Pending handover"
        ACCEPTED = "accepted", "Accepted"
        IN_PROGRESS = "in_progress", "In progress"
        READY = "ready", "Ready"
        COMPLETED = "completed", "Completed"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="projects")
    handover = models.OneToOneField(Handover, on_delete=models.SET_NULL, null=True, blank=True, related_name="project")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.DELIVERY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACCEPTED)
    manager = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="managed_projects")
    members = models.ManyToManyField("identity.Membership", blank=True, related_name="projects")
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    completion_checklist = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class MilestoneStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    READY = "ready", "Ready"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    IN_REVIEW = "in_review", "In review"
    ACCEPTED = "accepted", "Accepted"
    CANCELLED = "cancelled", "Cancelled"


class Milestone(TenantModel, Versioned):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)
    owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="milestones")
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=MilestoneStatus.choices, default=MilestoneStatus.PLANNED)
    depends_on = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="dependents")
    blocker_description = models.TextField(blank=True)
    blocker_next_owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    evidence = models.TextField(blank=True)
    submitted_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)
    override_reason = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)
    cancel_impact = models.TextField(blank=True)
    reopen_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "due_date"]


class MilestoneEvent(TenantModel):
    milestone = models.ForeignKey(Milestone, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(max_length=16)
    actor = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    note = models.TextField(blank=True)
    evidence_snapshot = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class ProjectChange(TenantModel):
    """Scope changes are recorded separately from defects (CRM08)."""

    class Kind(models.TextChoices):
        SCOPE_CHANGE = "scope_change", "Scope change"
        DEFECT = "defect", "Defect"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        FIXED = "fixed", "Fixed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="changes")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    raised_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    decided_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
