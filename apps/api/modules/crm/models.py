from django.db import models
from django.utils import timezone

from modules.common.models import TenantModel, Versioned


class Contact(TenantModel):
    """A person (and their company) we talk to. Reused when a lead becomes a client."""

    name = models.CharField(max_length=200, blank=True)
    company_name = models.CharField(max_length=200, blank=True)
    title = models.CharField(max_length=120, blank=True)
    email = models.CharField(max_length=254, blank=True)
    email_normalized = models.CharField(max_length=254, blank=True, db_index=True)
    phone = models.CharField(max_length=64, blank=True)
    phone_normalized = models.CharField(max_length=32, blank=True, db_index=True)
    linkedin_url = models.CharField(max_length=300, blank=True)
    website = models.CharField(max_length=300, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO country used for phone normalisation")
    notes = models.TextField(blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["company_name", "name"]

    def __str__(self):
        return self.name or self.company_name or self.email or str(self.pk)

    @property
    def label(self):
        if self.name and self.company_name:
            return f"{self.name} · {self.company_name}"
        return self.name or self.company_name or self.email or self.phone or "Unnamed contact"


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    ASSIGNED = "assigned", "Assigned"
    CONTACTING = "contacting", "Contacting"
    QUALIFIED = "qualified", "Qualified"
    NURTURE = "nurture", "Nurture"
    DISQUALIFIED = "disqualified", "Disqualified"


class Lead(TenantModel, Versioned):
    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="leads")
    owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_leads")
    shared_with = models.ManyToManyField("identity.Membership", blank=True, related_name="shared_leads")
    source = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=20, choices=LeadStatus.choices, default=LeadStatus.NEW)
    status_changed_at = models.DateTimeField(default=timezone.now)
    need = models.TextField(blank=True, help_text="Qualification: what they need")
    fit = models.TextField(blank=True, help_text="Qualification: why we fit")
    nurture_review_date = models.DateField(null=True, blank=True)
    disqualify_reason = models.TextField(blank=True)
    next_action = models.CharField(max_length=300, blank=True)
    next_action_due = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    import_batch = models.ForeignKey("crm.ImportBatch", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads")
    import_row = models.PositiveIntegerField(null=True, blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["import_batch", "import_row"], name="uniq_lead_import_row"),
        ]


class Stage(models.TextChoices):
    DISCOVERY = "discovery", "Discovery"
    QUALIFIED = "qualified", "Qualified"
    PROPOSAL = "proposal", "Proposal"
    NEGOTIATION = "negotiation", "Negotiation"
    WON = "won", "Won"
    LOST = "lost", "Lost"


OPEN_STAGES = [Stage.DISCOVERY, Stage.QUALIFIED, Stage.PROPOSAL, Stage.NEGOTIATION]


class Opportunity(TenantModel, Versioned):
    """One potential sale. A contact can have several."""

    contact = models.ForeignKey(Contact, on_delete=models.PROTECT, related_name="opportunities")
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="opportunities")
    title = models.CharField(max_length=200)
    service = models.CharField(max_length=200, blank=True)
    owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="owned_opportunities")
    shared_with = models.ManyToManyField("identity.Membership", blank=True, related_name="shared_opportunities")
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.DISCOVERY)
    stage_changed_at = models.DateTimeField(default=timezone.now)
    value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    expected_close_date = models.DateField(null=True, blank=True)
    next_action = models.CharField(max_length=300, blank=True)
    next_action_due = models.DateTimeField(null=True, blank=True)
    scope_reference = models.TextField(blank=True, help_text="Proposal / scope document reference")
    lost_reason = models.TextField(blank=True)
    commercial_decision = models.TextField(blank=True, help_text="Recorded commercial decision when won")
    closed_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "opportunities"

    @property
    def is_open(self):
        return self.stage in OPEN_STAGES


class StageHistory(TenantModel):
    entity_type = models.CharField(max_length=20)  # lead | opportunity
    entity_id = models.UUIDField(db_index=True)
    from_stage = models.CharField(max_length=20, blank=True)
    to_stage = models.CharField(max_length=20)
    reason = models.TextField(blank=True)
    actor = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]


class ActivityKind(models.TextChoices):
    CALL = "call", "Call"
    EMAIL = "email", "Email"
    MEETING = "meeting", "Meeting"
    LINKEDIN = "linkedin", "LinkedIn"
    NOTE = "note", "Note"


class Verification(models.TextChoices):
    SELF_REPORTED = "self_reported", "Self-reported"
    PROVIDER_CONFIRMED = "provider_confirmed", "Provider-confirmed"


class Activity(TenantModel):
    kind = models.CharField(max_length=16, choices=ActivityKind.choices)
    contact = models.ForeignKey(Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    lead = models.ForeignKey(Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    client = models.ForeignKey("work.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    subject = models.CharField(max_length=200, blank=True)
    outcome = models.CharField(max_length=300, blank=True)
    body = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="activities")
    verification = models.CharField(max_length=24, choices=Verification.choices, default=Verification.SELF_REPORTED)
    provider_reference = models.CharField(max_length=200, blank=True)
    source_url = models.CharField(max_length=300, blank=True)
    next_action = models.CharField(max_length=300, blank=True)
    corrected = models.BooleanField(default=False)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name_plural = "activities"

    @property
    def recorded_at(self):
        return self.created_at


class ActivityRevision(TenantModel):
    """Correction trail: the previous values of an edited activity (CRM04)."""

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="revisions")
    editor = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    previous = models.JSONField()
    reason = models.TextField()

    class Meta:
        ordering = ["-created_at"]


class ImportBatch(TenantModel):
    class Status(models.TextChoices):
        PREVIEWED = "previewed", "Previewed"
        CONFIRMED = "confirmed", "Confirmed"

    file_name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PREVIEWED)
    raw_csv = models.TextField()
    headers = models.JSONField(default=list)
    row_count = models.PositiveIntegerField(default=0)
    mapping = models.JSONField(default=dict, blank=True)
    default_owner = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    counts = models.JSONField(default=dict, blank=True)
    errors_csv = models.TextField(blank=True)
    created_by = models.ForeignKey("identity.Membership", on_delete=models.SET_NULL, null=True, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["workspace", "sha256"], name="uniq_import_file")]
