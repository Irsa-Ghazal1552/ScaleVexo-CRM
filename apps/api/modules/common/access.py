"""Record-level visibility rules (CRM01).

Every list and detail endpoint starts from one of these querysets, so a user
cannot reach another person's private record by editing a URL: records outside
the scope simply do not exist for them (HTTP 404).
"""
from django.db.models import Q

from modules.identity.models import DELIVERY_ROLES, SALES_ROLES, Membership, Role


def _ws(model, m):
    return model.objects.filter(workspace=m.workspace)


def leads_for(m):
    from modules.crm.models import Lead

    qs = _ws(Lead, m).filter(archived=False)
    if m.role in (Role.OWNER, Role.SALES_MANAGER):
        return qs
    if m.role == Role.SALES_REP:
        return qs.filter(Q(owner=m) | Q(shared_with=m)).distinct()
    return qs.none()


def opportunities_for(m):
    from modules.crm.models import Opportunity

    qs = _ws(Opportunity, m).filter(archived=False)
    if m.role in (Role.OWNER, Role.SALES_MANAGER):
        return qs
    if m.role == Role.SALES_REP:
        return qs.filter(Q(owner=m) | Q(shared_with=m) | Q(lead__owner=m)).distinct()
    if m.role in DELIVERY_ROLES:
        # Authorised delivery staff can read the sales history of their clients.
        clients = clients_for(m).values("id")
        return qs.filter(handover__client__in=clients).distinct()
    return qs.none()


def clients_for(m):
    from modules.work.models import Client

    qs = _ws(Client, m)
    if m.role in (Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER):
        return qs
    if m.role == Role.SALES_REP:
        return qs.filter(Q(account_owner=m) | Q(handovers__opportunity__owner=m)).distinct()
    if m.role == Role.DELIVERY_EMPLOYEE:
        return qs.filter(
            Q(delivery_manager=m)
            | Q(projects__members=m)
            | Q(projects__manager=m)
            | Q(projects__milestones__owner=m)
            | Q(handovers__delivery_owner=m)
        ).distinct()
    return qs.none()


def projects_for(m):
    from modules.work.models import Project

    qs = _ws(Project, m)
    if m.role in (Role.OWNER, Role.DELIVERY_MANAGER, Role.SALES_MANAGER):
        return qs
    if m.role == Role.SALES_REP:
        return qs.filter(client__in=clients_for(m).values("id")).distinct()
    if m.role == Role.DELIVERY_EMPLOYEE:
        return qs.filter(
            Q(manager=m) | Q(members=m) | Q(milestones__owner=m) | Q(tasks__owner=m) | Q(handover__delivery_owner=m)
        ).distinct()
    return qs.none()


def tickets_for(m):
    from modules.support.models import Ticket

    qs = _ws(Ticket, m)
    if m.role in (Role.OWNER, Role.DELIVERY_MANAGER):
        return qs
    if m.role == Role.ADMIN:
        return qs.filter(Q(owner=m) | Q(created_by=m))
    return qs.filter(
        Q(owner=m) | Q(created_by=m) | Q(waiting_next_owner=m) | Q(project__in=projects_for(m).values("id"))
    ).distinct()


def team_members_visible(m):
    """Memberships whose work this person may supervise."""
    qs = Membership.objects.filter(workspace=m.workspace)
    if m.role == Role.OWNER:
        return qs
    if m.role == Role.SALES_MANAGER:
        return qs.filter(role__in=SALES_ROLES)
    if m.role == Role.DELIVERY_MANAGER:
        return qs.filter(role__in=DELIVERY_ROLES)
    return qs.filter(pk=m.pk)


def tasks_for(m):
    from modules.work.models import Task

    qs = _ws(Task, m)
    if m.role == Role.OWNER:
        return qs
    return qs.filter(Q(owner=m) | Q(owner__in=team_members_visible(m)) | Q(created_by=m)).distinct()


def activities_for(m):
    from modules.crm.models import Activity

    qs = _ws(Activity, m)
    if m.role in (Role.OWNER, Role.SALES_MANAGER):
        return qs
    return qs.filter(
        Q(author=m)
        | Q(lead__in=leads_for(m).values("id"))
        | Q(opportunity__in=opportunities_for(m).values("id"))
        | Q(client__in=clients_for(m).values("id"))
    ).distinct()


def can_see_commercials(m):
    """Delivery employees do not see deal values and receipts."""
    return m.role in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP, Role.DELIVERY_MANAGER)
