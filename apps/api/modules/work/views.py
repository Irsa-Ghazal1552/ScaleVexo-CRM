from datetime import timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import access, audit
from modules.common.errors import BusinessRuleError
from modules.crm.serializers import ActivitySerializer, OpportunitySerializer
from modules.identity.auth import get_membership, require_role
from modules.identity.models import Membership, Role

from . import services
from .models import Client, Handover, Milestone, Project, ProjectChange, ProjectTemplate
from .serializers import (
    ClientSerializer,
    HandoverSerializer,
    MilestoneSerializer,
    ProjectChangeSerializer,
    ProjectSerializer,
    ProjectTemplateSerializer,
    TaskSerializer,
)


def _task_qs(m):
    return access.tasks_for(m).select_related(
        "owner__user", "opportunity__contact", "lead__contact", "ticket__client", "project__client", "milestone__project__client", "client"
    ).prefetch_related("reschedules__actor__user")


class TodayView(APIView):
    """Role-specific home: what this person can act on now (CRM05)."""

    def get(self, request):
        from modules.automation.models import Alert
        from modules.automation.serializers import AlertSerializer

        m = get_membership(request)
        now = timezone.now()
        mine = _task_qs(m).filter(owner=m)
        open_mine = mine.filter(status__in=["open", "blocked"])
        data = {
            "overdue": TaskSerializer(open_mine.filter(status="open", due_at__lt=now).order_by("due_at")[:100], many=True).data,
            "due_today": TaskSerializer(open_mine.filter(status="open", due_at__gte=now, due_at__lte=now + timedelta(hours=24)).order_by("due_at"), many=True).data,
            "upcoming": TaskSerializer(open_mine.filter(status="open", due_at__gt=now + timedelta(hours=24), due_at__lte=now + timedelta(days=7)).order_by("due_at")[:50], many=True).data,
            "blocked": TaskSerializer(open_mine.filter(status="blocked"), many=True).data,
            "alerts": AlertSerializer(Alert.objects.filter(workspace=m.workspace, recipient=m).exclude(status="resolved")[:50], many=True).data,
            "completed_today": mine.filter(status="done", completed_at__gte=now - timedelta(hours=24)).count(),
        }
        if m.role in (Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER):
            team = access.team_members_visible(m).exclude(pk=m.pk)
            data["team_overdue"] = TaskSerializer(
                _task_qs(m).filter(owner__in=team, status="open", due_at__lt=now).order_by("due_at")[:50], many=True).data
        if m.role in (Role.DELIVERY_MANAGER, Role.OWNER, Role.DELIVERY_EMPLOYEE):
            hq = Handover.objects.filter(workspace=m.workspace, status__in=["pending", "exception"])
            if m.role == Role.DELIVERY_EMPLOYEE:
                hq = hq.filter(delivery_owner=m)
            data["handovers"] = HandoverSerializer(hq.select_related("opportunity__owner__user", "client", "delivery_owner__user"), many=True, context={"membership": m}).data
        return Response(data)


class TasksView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = _task_qs(m)
        p = request.query_params
        if p.get("owner") == "me":
            qs = qs.filter(owner=m)
        elif p.get("owner"):
            qs = qs.filter(owner_id=p["owner"])
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        for key in ("lead", "opportunity", "client", "project", "ticket", "milestone"):
            if p.get(key):
                qs = qs.filter(**{f"{key}_id": p[key]})
        if p.get("overdue") == "1":
            qs = qs.filter(status="open", due_at__lt=timezone.now())
        from modules.crm.views import paginate

        return paginate(self, request, qs.order_by("due_at"), TaskSerializer)

    def post(self, request):
        m = get_membership(request)
        return Response(TaskSerializer(services.create_task(m, request.data)).data, status=201)


class TaskActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        task = get_object_or_404(access.tasks_for(m), pk=pk)
        if action == "complete":
            task, next_task = services.complete_task(m, task, request.data)
            return Response({"task": TaskSerializer(task).data, "next_task": TaskSerializer(next_task).data if next_task else None})
        if action == "reschedule":
            task = services.reschedule_task(m, task, request.data)
        elif action == "block":
            task = services.set_task_blocked(m, task, request.data, True)
        elif action == "unblock":
            task = services.set_task_blocked(m, task, request.data, False)
        elif action == "cancel":
            task = services.cancel_task(m, task, request.data)
        else:
            raise BusinessRuleError("Unknown action.")
        return Response(TaskSerializer(task).data)


# ---------------------------------------------------------------- clients
class ClientsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = access.clients_for(m).select_related("primary_contact", "account_owner__user", "delivery_manager__user")
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(primary_contact__name__icontains=q) | Q(primary_contact__email__icontains=q))
        from modules.crm.views import paginate

        return paginate(self, request, qs, ClientSerializer)


class ClientDetailView(APIView):
    def get(self, request, pk):
        from modules.support.serializers import TicketSerializer

        m = get_membership(request)
        client = get_object_or_404(access.clients_for(m), pk=pk)
        data = ClientSerializer(client).data
        data["projects"] = ProjectSerializer(access.projects_for(m).filter(client=client).prefetch_related("milestones", "members__user"), many=True).data
        data["tickets"] = TicketSerializer(access.tickets_for(m).filter(client=client)[:50], many=True).data
        data["handovers"] = HandoverSerializer(client.handovers.all(), many=True, context={"membership": m}).data
        # Sales history stays available to authorised delivery staff (CRM07).
        opps = access.opportunities_for(m).filter(Q(handover__client=client) | Q(contact=client.primary_contact)).distinct()
        data["opportunities"] = OpportunitySerializer(opps, many=True, context={"membership": m}).data
        data["activities"] = ActivitySerializer(
            access.activities_for(m).filter(Q(client=client) | Q(opportunity__in=opps) | Q(contact=client.primary_contact)).distinct()[:100], many=True).data
        if access.can_see_commercials(m):
            from modules.reporting.serializers import ReceiptSerializer

            data["receipts"] = ReceiptSerializer(client.receipts.all(), many=True).data
        return Response(data)

    def patch(self, request, pk):
        m = get_membership(request)
        client = get_object_or_404(access.clients_for(m), pk=pk)
        require_role(m, Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER)
        for f in ("name", "notes", "status"):
            if f in request.data:
                setattr(client, f, request.data[f])
        if "delivery_manager_id" in request.data:
            client.delivery_manager = Membership.objects.filter(workspace=m.workspace, pk=request.data["delivery_manager_id"]).first()
        if client.status not in Client.Status.values:
            raise BusinessRuleError("Unknown status.")
        client.save()
        audit.record(m.workspace, m, "client.updated", client, f"Updated client {client.name}")
        return Response(ClientSerializer(client).data)


# ---------------------------------------------------------------- handovers
def _handover_qs(m):
    qs = Handover.objects.filter(workspace=m.workspace).select_related("opportunity__owner__user", "client", "delivery_owner__user")
    if m.role in (Role.OWNER, Role.DELIVERY_MANAGER, Role.SALES_MANAGER):
        return qs
    return qs.filter(Q(delivery_owner=m) | Q(opportunity__owner=m) | Q(created_by=m))


class HandoversView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = _handover_qs(m)
        if request.query_params.get("status"):
            qs = qs.filter(status__in=request.query_params["status"].split(","))
        return Response(HandoverSerializer(qs[:200], many=True, context={"membership": m}).data)


class HandoverActionView(APIView):
    def get(self, request, pk, action=None):
        m = get_membership(request)
        h = get_object_or_404(_handover_qs(m), pk=pk)
        return Response(HandoverSerializer(h, context={"membership": m}).data)

    def post(self, request, pk, action):
        m = get_membership(request)
        h = get_object_or_404(_handover_qs(m), pk=pk)
        fn = {"accept": services.accept_handover, "return": services.return_handover, "resubmit": services.resubmit_handover}.get(action)
        if fn is None:
            raise BusinessRuleError("Unknown action.")
        h = fn(m, h, request.data)
        return Response(HandoverSerializer(Handover.objects.get(pk=h.pk), context={"membership": m}).data)


# ---------------------------------------------------------------- projects
class ProjectsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = access.projects_for(m).select_related("client", "manager__user").prefetch_related("milestones", "members__user")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("mine") == "1":
            qs = qs.filter(Q(manager=m) | Q(members=m)).distinct()
        if p.get("q"):
            qs = qs.filter(Q(name__icontains=p["q"]) | Q(client__name__icontains=p["q"]))
        from modules.crm.views import paginate

        return paginate(self, request, qs, ProjectSerializer)

    def post(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, Role.DELIVERY_MANAGER)
        client = get_object_or_404(access.clients_for(m), pk=request.data.get("client_id"))
        name = (request.data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Give the project a name.", fields={"name": ["Required"]})
        template = ProjectTemplate.objects.filter(workspace=m.workspace, pk=request.data.get("template_id")).first() if request.data.get("template_id") else None
        manager = services._member(m, request.data.get("manager_id") or m.pk, "manager_id")
        project = services.create_project_from_template(m, client, None, template, manager, name=name, kind=Project.Kind.DELIVERY)
        return Response(ProjectSerializer(project).data, status=201)


class ProjectDetailView(APIView):
    def get(self, request, pk):
        from modules.support.serializers import TicketSerializer

        m = get_membership(request)
        project = get_object_or_404(access.projects_for(m), pk=pk)
        data = ProjectSerializer(project).data
        data["milestones"] = MilestoneSerializer(project.milestones.prefetch_related("depends_on", "events__actor__user"), many=True).data
        data["changes"] = ProjectChangeSerializer(project.changes.all(), many=True).data
        data["tasks"] = TaskSerializer(_task_qs(m).filter(project=project), many=True).data
        data["tickets"] = TicketSerializer(access.tickets_for(m).filter(project=project), many=True).data
        data["handover"] = HandoverSerializer(project.handover, context={"membership": m}).data if project.handover_id else None
        return Response(data)

    def patch(self, request, pk):
        m = get_membership(request)
        project = get_object_or_404(access.projects_for(m), pk=pk)
        if not services._is_reviewer(m, project):
            raise BusinessRuleError("Only the delivery manager can edit the project.")
        from modules.common.errors import require_version

        require_version(project, request.data.get("version"))
        for f in ("name",):
            if f in request.data:
                setattr(project, f, request.data[f])
        for f in ("start_date", "due_date"):
            if f in request.data:
                setattr(project, f, parse_date(request.data[f]) if request.data[f] else None)
        if "manager_id" in request.data:
            project.manager = services._member(m, request.data["manager_id"], "manager_id")
        if "member_ids" in request.data:
            project.members.set(Membership.objects.filter(workspace=m.workspace, pk__in=request.data["member_ids"] or [], status="active"))
        project.bump()
        project.save()
        audit.record(m.workspace, m, "project.updated", project, f"Updated project {project.name}")
        return Response(ProjectSerializer(project).data)


class ProjectActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        project = get_object_or_404(access.projects_for(m), pk=pk)
        if action == "complete":
            return Response(ProjectSerializer(services.complete_project(m, project, request.data)).data)
        if action == "milestones":
            if not services._is_reviewer(m, project):
                raise BusinessRuleError("Only the delivery manager can add milestones.")
            title = (request.data.get("title") or "").strip()
            if not title:
                raise BusinessRuleError("Give the milestone a title.", fields={"title": ["Required"]})
            ms = Milestone.objects.create(
                workspace=m.workspace, project=project, title=title, description=request.data.get("description") or "",
                order=project.milestones.count(),
                due_date=parse_date(request.data["due_date"]) if request.data.get("due_date") else None,
                owner=services._member(m, request.data.get("owner_id"), "owner_id") if request.data.get("owner_id") else None,
            )
            deps = Milestone.objects.filter(project=project, pk__in=request.data.get("depends_on") or [])
            ms.depends_on.set(deps)
            audit.record(m.workspace, m, "milestone.created", ms, f"Milestone '{title}' added to {project.name}")
            return Response(MilestoneSerializer(ms).data, status=201)
        if action == "changes":
            return Response(ProjectChangeSerializer(services.add_project_change(m, project, request.data)).data, status=201)
        raise BusinessRuleError("Unknown action.")


class MilestoneView(APIView):
    def _get(self, m, pk):
        return get_object_or_404(Milestone.objects.filter(project__in=access.projects_for(m).values("id")), pk=pk)

    def patch(self, request, pk):
        m = get_membership(request)
        ms = self._get(m, pk)
        if not services._is_reviewer(m, ms.project):
            raise BusinessRuleError("Only the delivery manager can edit milestone details.")
        from modules.common.errors import require_version

        require_version(ms, request.data.get("version"))
        for f in ("title", "description"):
            if f in request.data:
                setattr(ms, f, request.data[f] or "")
        if "due_date" in request.data:
            ms.due_date = parse_date(request.data["due_date"]) if request.data["due_date"] else None
        if "owner_id" in request.data:
            ms.owner = services._member(m, request.data["owner_id"], "owner_id") if request.data["owner_id"] else None
        if "depends_on" in request.data:
            deps = Milestone.objects.filter(project=ms.project, pk__in=request.data["depends_on"] or []).exclude(pk=ms.pk)
            ms.depends_on.set(deps)
        ms.bump()
        ms.save()
        audit.record(m.workspace, m, "milestone.updated", ms, f"Updated milestone '{ms.title}'")
        return Response(MilestoneSerializer(ms).data)

    def post(self, request, pk):
        m = get_membership(request)
        ms = self._get(m, pk)
        ms = services.transition_milestone(m, ms, request.data.get("status"), request.data)
        return Response(MilestoneSerializer(Milestone.objects.get(pk=ms.pk)).data)


class ProjectChangeView(APIView):
    def post(self, request, pk):
        m = get_membership(request)
        change = get_object_or_404(ProjectChange.objects.filter(project__in=access.projects_for(m).values("id")), pk=pk)
        return Response(ProjectChangeSerializer(services.decide_project_change(m, change, request.data)).data)


class TemplatesView(APIView):
    def get(self, request):
        m = get_membership(request)
        return Response(ProjectTemplateSerializer(ProjectTemplate.objects.filter(workspace=m.workspace), many=True).data)

    def post(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, Role.ADMIN, Role.DELIVERY_MANAGER)
        ser = ProjectTemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        _validate_template(ser.validated_data.get("milestones") or [])
        if ser.validated_data.get("is_default"):
            ProjectTemplate.objects.filter(workspace=m.workspace).update(is_default=False)
        t = ser.save(workspace=m.workspace)
        audit.record(m.workspace, m, "template.created", t, f"Template {t.name} created")
        return Response(ProjectTemplateSerializer(t).data, status=201)


class TemplateDetailView(APIView):
    def put(self, request, pk):
        m = get_membership(request)
        require_role(m, Role.OWNER, Role.ADMIN, Role.DELIVERY_MANAGER)
        t = get_object_or_404(ProjectTemplate, workspace=m.workspace, pk=pk)
        ser = ProjectTemplateSerializer(t, data=request.data)
        ser.is_valid(raise_exception=True)
        _validate_template(ser.validated_data.get("milestones") or [])
        if ser.validated_data.get("is_default"):
            ProjectTemplate.objects.filter(workspace=m.workspace).exclude(pk=t.pk).update(is_default=False)
        ser.save()
        audit.record(m.workspace, m, "template.updated", t, f"Template {t.name} updated")
        return Response(ser.data)


def _validate_template(items):
    if not isinstance(items, list):
        raise BusinessRuleError("Milestones must be a list.")
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not str(item.get("title") or "").strip():
            raise BusinessRuleError(f"Milestone {i + 1} needs a title.")
        try:
            int(item.get("offset_days") or 0)
        except (TypeError, ValueError):
            raise BusinessRuleError(f"Milestone {i + 1}: offset days must be a number.")
        for d in item.get("depends_on") or []:
            if not isinstance(d, int) or d < 0 or d >= len(items) or d == i:
                raise BusinessRuleError(f"Milestone {i + 1}: invalid dependency.")
