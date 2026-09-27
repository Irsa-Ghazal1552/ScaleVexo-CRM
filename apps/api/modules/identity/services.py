from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from modules.common import audit
from modules.common.errors import BusinessRuleError

from .models import Invitation, Membership, Role, Workspace

User = get_user_model()

DEFAULT_ONBOARDING_TEMPLATE = [
    {"title": "Kick-off call and access checklist", "offset_days": 3, "depends_on": []},
    {"title": "Requirements and scope confirmation", "offset_days": 7, "depends_on": [0]},
    {"title": "First delivery milestone", "offset_days": 21, "depends_on": [1]},
    {"title": "Client review and acceptance", "offset_days": 28, "depends_on": [2]},
]


def ensure_workspace_defaults(workspace):
    from modules.ai.models import AISettings
    from modules.automation.models import RuleDefinition
    from modules.automation.templates import RULE_TEMPLATES
    from modules.work.models import ProjectTemplate

    for t in RULE_TEMPLATES:
        RuleDefinition.objects.get_or_create(
            workspace=workspace,
            code=t["code"],
            defaults={k: t[k] for k in ("name", "trigger", "conditions", "action", "explanation", "params")},
        )
    if not ProjectTemplate.objects.filter(workspace=workspace).exists():
        ProjectTemplate.objects.create(
            workspace=workspace,
            name="Standard client onboarding",
            description="Default onboarding plan created when a deal is won.",
            milestones=DEFAULT_ONBOARDING_TEMPLATE,
            is_default=True,
        )
    AISettings.objects.get_or_create(workspace=workspace)


@transaction.atomic
def create_workspace(name, owner_email, owner_password, owner_first_name="", owner_last_name="", tz="Asia/Karachi"):
    workspace = Workspace.objects.create(name=name, timezone=tz)
    user = User.objects.filter(username__iexact=owner_email).first()
    if user is None:
        user = User.objects.create_user(
            username=owner_email.lower(), email=owner_email.lower(), password=owner_password,
            first_name=owner_first_name, last_name=owner_last_name,
        )
    owner = Membership.objects.create(workspace=workspace, user=user, role=Role.OWNER, title="CEO")
    ensure_workspace_defaults(workspace)
    audit.record(workspace, owner, "workspace.created", ("workspace", workspace.pk), f"Workspace {name} created")
    return workspace, owner


def create_invitation(actor, email, role, title="", days_valid=7):
    email = email.strip().lower()
    if role not in Role.values:
        raise BusinessRuleError("Unknown role.")
    if role == Role.OWNER and actor.role != Role.OWNER:
        raise BusinessRuleError("Only the workspace owner can invite another owner.")
    if Membership.objects.filter(workspace=actor.workspace, user__username__iexact=email).exists():
        raise BusinessRuleError("This person is already a member of the workspace.")
    inv = Invitation.objects.create(
        workspace=actor.workspace, email=email, role=role, title=title, invited_by=actor,
        expires_at=timezone.now() + timedelta(days=days_valid),
    )
    audit.record(actor.workspace, actor, "invitation.created", inv, f"Invited {email} as {role}")
    return inv


@transaction.atomic
def accept_invitation(token, first_name, last_name, password):
    inv = Invitation.objects.select_for_update().filter(token=token).first()
    if inv is None or not inv.is_usable:
        raise BusinessRuleError("This invitation link is invalid or has expired.", code="invalid_invitation")
    user = User.objects.filter(username__iexact=inv.email).first()
    if user is None:
        user = User.objects.create_user(
            username=inv.email, email=inv.email, password=password, first_name=first_name, last_name=last_name
        )
    membership, _ = Membership.objects.get_or_create(
        workspace=inv.workspace, user=user, defaults={"role": inv.role, "title": inv.title}
    )
    inv.accepted_at = timezone.now()
    inv.save(update_fields=["accepted_at"])
    audit.record(inv.workspace, membership, "invitation.accepted", inv, f"{inv.email} joined as {inv.role}")
    return membership


def suspend_member(actor, member, reason):
    if not reason.strip():
        raise BusinessRuleError("A reason is required to suspend access.")
    if member.pk == actor.pk:
        raise BusinessRuleError("You cannot suspend yourself.")
    if member.role == Role.OWNER and actor.role != Role.OWNER:
        raise BusinessRuleError("Only an owner can suspend another owner.")
    member.status = Membership.Status.SUSPENDED
    member.suspended_at = timezone.now()
    member.suspended_reason = reason
    member.save(update_fields=["status", "suspended_at", "suspended_reason"])
    # Existing sessions are rejected on their next request by MembershipSessionAuthentication.
    audit.record(actor.workspace, actor, "member.suspended", member, f"Suspended {member.display_name}", {"reason": reason})
    return member


def reactivate_member(actor, member):
    member.status = Membership.Status.ACTIVE
    member.suspended_at = None
    member.save(update_fields=["status", "suspended_at"])
    audit.record(actor.workspace, actor, "member.reactivated", member, f"Reactivated {member.display_name}")
    return member


@transaction.atomic
def reassign_work(actor, from_member, to_member, reason):
    """Transfer open work. Original activity authors and history are preserved (CRM01)."""
    from modules.crm.models import OPEN_STAGES, Lead, Opportunity
    from modules.support.models import Ticket
    from modules.work.models import Task

    if not reason.strip():
        raise BusinessRuleError("A reason is required to transfer work.")
    if not to_member.is_active:
        raise BusinessRuleError("Work cannot be transferred to a suspended member.")
    if from_member.pk == to_member.pk:
        raise BusinessRuleError("Choose a different person to receive the work.")
    ws = actor.workspace
    counts = {
        "leads": Lead.objects.filter(workspace=ws, owner=from_member, archived=False).exclude(status="disqualified").update(owner=to_member),
        "opportunities": Opportunity.objects.filter(workspace=ws, owner=from_member, stage__in=OPEN_STAGES).update(owner=to_member),
        "tasks": Task.objects.filter(workspace=ws, owner=from_member, status__in=["open", "blocked"]).update(owner=to_member),
        "tickets": Ticket.objects.filter(workspace=ws, owner=from_member).exclude(status__in=["resolved", "closed"]).update(owner=to_member),
    }
    audit.record(
        ws, actor, "work.reassigned", from_member,
        f"Transferred work from {from_member.display_name} to {to_member.display_name}",
        {"reason": reason, "to": str(to_member.pk), "counts": counts},
    )
    return counts
