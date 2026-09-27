from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import access
from modules.common.errors import BusinessRuleError
from modules.identity.auth import get_membership

from . import services
from .serializers import TicketEventSerializer, TicketNoteSerializer, TicketSerializer


class TicketsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = access.tickets_for(m).select_related("owner__user", "created_by__user", "client", "project", "waiting_next_owner__user")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("open") == "1":
            qs = qs.exclude(status__in=["resolved", "closed"])
        if p.get("severity"):
            qs = qs.filter(severity__in=p["severity"].split(","))
        if p.get("owner") == "me":
            qs = qs.filter(owner=m)
        if p.get("client"):
            qs = qs.filter(client_id=p["client"])
        if p.get("project"):
            qs = qs.filter(project_id=p["project"])
        if p.get("q"):
            q = p["q"]
            cond = Q(title__icontains=q) | Q(description__icontains=q) | Q(client__name__icontains=q)
            if q.isdigit():
                cond |= Q(number=int(q))
            qs = qs.filter(cond)
        from modules.crm.views import paginate

        return paginate(self, request, qs, TicketSerializer)

    def post(self, request):
        m = get_membership(request)
        return Response(TicketSerializer(services.create_ticket(m, request.data)).data, status=201)


class TicketDetailView(APIView):
    def get(self, request, pk):
        m = get_membership(request)
        t = get_object_or_404(access.tickets_for(m), pk=pk)
        data = TicketSerializer(t).data
        data["notes"] = TicketNoteSerializer(t.notes.select_related("author__user"), many=True).data
        data["events"] = TicketEventSerializer(t.events.select_related("actor__user"), many=True).data
        return Response(data)

    def patch(self, request, pk):
        m = get_membership(request)
        t = get_object_or_404(access.tickets_for(m), pk=pk)
        return Response(TicketSerializer(services.update_ticket(m, t, request.data)).data)


class TicketActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        t = get_object_or_404(access.tickets_for(m), pk=pk)
        if action == "status":
            t = services.transition_ticket(m, t, request.data.get("status"), request.data)
            return Response(TicketSerializer(t).data)
        if action == "notes":
            note = services.add_note(m, t, request.data)
            return Response(TicketNoteSerializer(note).data, status=201)
        raise BusinessRuleError("Unknown action.")
