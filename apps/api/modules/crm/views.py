from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import access
from modules.common.errors import BusinessRuleError
from modules.common.pagination import StandardPagination
from modules.identity.auth import SALES_ALL, get_membership, require_role
from modules.identity.models import Membership

from . import services
from .models import OPEN_STAGES, Contact, ImportBatch, Opportunity, StageHistory
from .serializers import (
    ActivitySerializer, ContactSerializer, ImportBatchSerializer, LeadSerializer, OpportunitySerializer,
    StageHistorySerializer,
)


def paginate(view, request, qs, serializer_cls, **ctx):
    pager = StandardPagination()
    page = pager.paginate_queryset(qs, request, view=view)
    return pager.get_paginated_response(serializer_cls(page, many=True, context=ctx).data)


# ---------------------------------------------------------------- contacts
class ContactsView(APIView):
    def get(self, request):
        m = get_membership(request)
        if m.role not in ("owner", "sales_manager", "sales_rep"):
            return Response({"count": 0, "results": []})
        qs = Contact.objects.filter(workspace=m.workspace, archived=False)
        if m.role == "sales_rep":
            qs = qs.filter(Q(leads__in=access.leads_for(m)) | Q(opportunities__in=access.opportunities_for(m))).distinct()
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(company_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        return paginate(self, request, qs, ContactSerializer)


class ContactDuplicateCheckView(APIView):
    def get(self, request):
        m = get_membership(request)
        email = services.normalize_email(request.query_params.get("email"))
        phone = services.normalize_phone(request.query_params.get("phone"), request.query_params.get("country", ""))
        exact = services.find_exact_duplicates(m.workspace, email, phone)
        similar = services.similar_contacts(m.workspace, request.query_params.get("name", ""), request.query_params.get("company", ""))
        return Response({
            "exact": ContactSerializer(exact[:5], many=True).data,
            "similar": ContactSerializer([c for c in similar if c not in exact], many=True).data,
        })


class ContactDetailView(APIView):
    def _get(self, m, pk):
        qs = Contact.objects.filter(workspace=m.workspace)
        contact = get_object_or_404(qs, pk=pk)
        visible = (
            m.role in SALES_ALL
            or access.leads_for(m).filter(contact=contact).exists()
            or access.opportunities_for(m).filter(contact=contact).exists()
            or access.clients_for(m).filter(primary_contact=contact).exists()
        )
        if not visible:
            from django.http import Http404

            raise Http404
        return contact

    def get(self, request, pk):
        m = get_membership(request)
        return Response(ContactSerializer(self._get(m, pk)).data)

    def patch(self, request, pk):
        m = get_membership(request)
        contact = self._get(m, pk)
        if m.role not in ("owner", "sales_manager", "sales_rep", "delivery_manager"):
            raise BusinessRuleError("You cannot edit contacts.")
        return Response(ContactSerializer(services.update_contact(m, contact, request.data)).data)


class ContactMergeView(APIView):
    def post(self, request):
        m = get_membership(request)
        require_role(m, *SALES_ALL)
        keep = get_object_or_404(Contact, workspace=m.workspace, pk=request.data.get("keep_id"))
        merge = get_object_or_404(Contact, workspace=m.workspace, pk=request.data.get("merge_id"))
        return Response(ContactSerializer(services.merge_contacts(m, keep, merge, request.data.get("reason"))).data)


# ---------------------------------------------------------------- leads
class LeadsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = access.leads_for(m).select_related("contact", "owner__user").prefetch_related("shared_with__user")
        p = request.query_params
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(contact__name__icontains=q) | Q(contact__company_name__icontains=q) | Q(contact__email__icontains=q)
                           | Q(contact__phone__icontains=q) | Q(source__icontains=q))
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("owner") == "me":
            qs = qs.filter(owner=m)
        elif p.get("owner") == "none":
            qs = qs.filter(owner__isnull=True)
        elif p.get("owner"):
            qs = qs.filter(owner_id=p["owner"])
        if p.get("source"):
            qs = qs.filter(source__iexact=p["source"])
        order = p.get("ordering") or "-created_at"
        if order.lstrip("-") in ("created_at", "status_changed_at", "next_action_due", "last_activity_at"):
            qs = qs.order_by(order)
        return paginate(self, request, qs, LeadSerializer)

    def post(self, request):
        m = get_membership(request)
        lead = services.create_lead(m, request.data)
        return Response(LeadSerializer(lead).data, status=201)


class LeadDetailView(APIView):
    def get(self, request, pk):
        m = get_membership(request)
        lead = get_object_or_404(access.leads_for(m), pk=pk)
        data = LeadSerializer(lead).data
        data["history"] = StageHistorySerializer(StageHistory.objects.filter(entity_type="lead", entity_id=lead.pk), many=True).data
        data["opportunities"] = OpportunitySerializer(access.opportunities_for(m).filter(lead=lead), many=True, context={"membership": m}).data
        return Response(data)

    def patch(self, request, pk):
        m = get_membership(request)
        lead = get_object_or_404(access.leads_for(m), pk=pk)
        return Response(LeadSerializer(services.update_lead(m, lead, request.data)).data)


class LeadActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        lead = get_object_or_404(access.leads_for(m), pk=pk)
        if action == "status":
            lead = services.change_lead_status(m, lead, request.data.get("status"), request.data)
        elif action == "share":
            require_role(m, *SALES_ALL)
            ids = request.data.get("member_ids") or []
            members = Membership.objects.filter(workspace=m.workspace, pk__in=ids, status="active")
            lead.shared_with.set(members)
            from modules.common import audit

            audit.record(m.workspace, m, "lead.shared", lead, f"Sharing updated for {lead.contact.label}", {"members": [str(x.pk) for x in members]})
        elif action == "archive":
            require_role(m, *SALES_ALL)
            reason = (request.data.get("reason") or "").strip()
            if not reason:
                raise BusinessRuleError("A reason is required to archive.")
            lead.archived = True
            lead.save(update_fields=["archived", "updated_at"])
            from modules.common import audit

            audit.record(m.workspace, m, "lead.archived", lead, f"Archived lead {lead.contact.label}", {"reason": reason})
            return Response({"ok": True})
        else:
            raise BusinessRuleError("Unknown action.")
        return Response(LeadSerializer(lead).data)


# ---------------------------------------------------------------- opportunities
def _opp_queryset(m, params):
    qs = access.opportunities_for(m).select_related("contact", "owner__user", "handover")
    if params.get("q"):
        q = params["q"]
        qs = qs.filter(Q(title__icontains=q) | Q(contact__name__icontains=q) | Q(contact__company_name__icontains=q) | Q(service__icontains=q))
    if params.get("stage"):
        qs = qs.filter(stage__in=params["stage"].split(","))
    if params.get("open") == "1":
        qs = qs.filter(stage__in=OPEN_STAGES)
    if params.get("owner") == "me":
        qs = qs.filter(owner=m)
    elif params.get("owner"):
        qs = qs.filter(owner_id=params["owner"])
    if params.get("currency"):
        qs = qs.filter(currency=params["currency"].upper())
    return qs


class OpportunitiesView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = _opp_queryset(m, request.query_params)
        order = request.query_params.get("ordering") or "-created_at"
        if order.lstrip("-") in ("created_at", "stage_changed_at", "value", "expected_close_date", "next_action_due"):
            qs = qs.order_by(order)
        return paginate(self, request, qs, OpportunitySerializer, membership=m)

    def post(self, request):
        m = get_membership(request)
        opp = services.create_opportunity(m, request.data)
        return Response(OpportunitySerializer(opp, context={"membership": m}).data, status=201)


class PipelineView(APIView):
    """Board data: every open deal plus deals closed in the last 30 days, with per-currency totals."""

    def get(self, request):
        from datetime import timedelta

        from django.utils import timezone

        m = get_membership(request)
        qs = _opp_queryset(m, request.query_params)
        recent = timezone.now() - timedelta(days=int(request.query_params.get("closed_days", 30)))
        qs = qs.filter(Q(stage__in=OPEN_STAGES) | Q(closed_at__gte=recent)).order_by("stage_changed_at")
        items = list(qs[:1000])
        summary = services.pipeline_summary(items)
        if not access.can_see_commercials(m):
            for s in summary["stages"]:
                s["totals"] = {}
        return Response({"summary": summary, "deals": OpportunitySerializer(items, many=True, context={"membership": m}).data})


class OpportunityDetailView(APIView):
    def get(self, request, pk):
        m = get_membership(request)
        opp = get_object_or_404(access.opportunities_for(m), pk=pk)
        data = OpportunitySerializer(opp, context={"membership": m}).data
        data["history"] = StageHistorySerializer(StageHistory.objects.filter(entity_type="opportunity", entity_id=opp.pk), many=True).data
        return Response(data)

    def patch(self, request, pk):
        m = get_membership(request)
        opp = get_object_or_404(access.opportunities_for(m), pk=pk)
        if m.role not in ("owner", "sales_manager", "sales_rep"):
            raise BusinessRuleError("Only the sales team can edit deals.")
        return Response(OpportunitySerializer(services.update_opportunity(m, opp, request.data), context={"membership": m}).data)


class OpportunityStageView(APIView):
    def post(self, request, pk):
        m = get_membership(request)
        opp = get_object_or_404(access.opportunities_for(m), pk=pk)
        if m.role not in ("owner", "sales_manager", "sales_rep"):
            raise BusinessRuleError("Only the sales team can move deals.")
        opp = services.move_stage(m, opp, request.data.get("stage"), request.data)
        opp = Opportunity.objects.get(pk=opp.pk)
        return Response(OpportunitySerializer(opp, context={"membership": m}).data)


# ---------------------------------------------------------------- activities
class ActivitiesView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = access.activities_for(m).select_related("author__user", "lead__contact", "opportunity", "client").prefetch_related("revisions")
        p = request.query_params
        for key in ("lead", "opportunity", "client", "contact"):
            if p.get(key):
                qs = qs.filter(**{f"{key}_id": p[key]})
        if p.get("author") == "me":
            qs = qs.filter(author=m)
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        return paginate(self, request, qs, ActivitySerializer)

    def post(self, request):
        m = get_membership(request)
        return Response(ActivitySerializer(services.log_activity(m, request.data)).data, status=201)


class ActivityDetailView(APIView):
    def patch(self, request, pk):
        m = get_membership(request)
        activity = get_object_or_404(access.activities_for(m), pk=pk)
        return Response(ActivitySerializer(services.edit_activity(m, activity, request.data)).data)


# ---------------------------------------------------------------- import / export
class ImportsView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *SALES_ALL)
        return Response(ImportBatchSerializer(ImportBatch.objects.filter(workspace=m.workspace)[:50], many=True).data)

    def post(self, request):
        m = get_membership(request)
        upload = request.FILES.get("file")
        if upload is not None:
            name, content = upload.name, upload.read()
        else:
            name, content = request.data.get("file_name") or "import.csv", request.data.get("content") or ""
        if not content:
            raise BusinessRuleError("Choose a CSV file to import.")
        batch, existing = services.import_preview(m, name, content)
        data = ImportBatchSerializer(batch).data
        data["already_uploaded"] = existing
        data["preview"] = services.preview_rows(batch)
        data["targets"] = services.IMPORT_TARGETS
        return Response(data, status=200 if existing else 201)


class ImportDetailView(APIView):
    def get(self, request, pk):
        m = get_membership(request)
        require_role(m, *SALES_ALL)
        batch = get_object_or_404(ImportBatch, workspace=m.workspace, pk=pk)
        data = ImportBatchSerializer(batch).data
        data["preview"] = services.preview_rows(batch)
        data["targets"] = services.IMPORT_TARGETS
        return Response(data)


class ImportConfirmView(APIView):
    def post(self, request, pk):
        m = get_membership(request)
        batch = get_object_or_404(ImportBatch, workspace=m.workspace, pk=pk)
        batch = services.import_confirm(m, batch, request.data.get("mapping") or {}, request.data.get("default_owner_id"))
        return Response(ImportBatchSerializer(batch).data)


class ImportErrorsView(APIView):
    def get(self, request, pk):
        m = get_membership(request)
        require_role(m, *SALES_ALL)
        batch = get_object_or_404(ImportBatch, workspace=m.workspace, pk=pk)
        response = HttpResponse(batch.errors_csv or "row,result,reason\n", content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="import-errors-{batch.pk}.csv"'
        return response


class LeadsExportView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *SALES_ALL)
        response = HttpResponse(services.export_leads_csv(m), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="leads.csv"'
        from modules.common import audit

        audit.record(m.workspace, m, "export.leads", ("workspace", m.workspace.pk), "Exported leads CSV")
        return response
