import json
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import access, audit
from modules.common.errors import BusinessRuleError
from modules.identity.auth import MANAGERS, get_membership, require_role
from modules.identity.models import Role

from . import services
from .models import CorrectionRequest, Receipt
from .serializers import CorrectionRequestSerializer, ReceiptSerializer


class OverviewView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *MANAGERS)
        return Response(services.overview(m, request.query_params))


class ReportView(APIView):
    def get(self, request, name):
        m = get_membership(request)
        require_role(m, *MANAGERS)
        return Response(services.report(m, name, request.query_params))


class AccountabilityView(APIView):
    def get(self, request):
        m = get_membership(request)
        return Response(services.accountability(m, request.query_params))


class ReceiptsView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, Role.SALES_MANAGER)
        qs = Receipt.objects.filter(workspace=m.workspace).select_related("client", "opportunity", "recorded_by__user")
        if request.query_params.get("client"):
            qs = qs.filter(client_id=request.query_params["client"])
        return Response(ReceiptSerializer(qs[:500], many=True).data)

    def post(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, message="Only the owner can record cash receipts.")
        d = request.data
        try:
            amount = Decimal(str(d.get("amount")))
        except (InvalidOperation, TypeError):
            raise BusinessRuleError("Enter the amount received.", fields={"amount": ["Required"]})
        if amount <= 0:
            raise BusinessRuleError("The amount must be greater than zero.", fields={"amount": ["Must be positive"]})
        currency = (d.get("currency") or "").strip().upper()
        if len(currency) != 3:
            raise BusinessRuleError("Choose the currency.", fields={"currency": ["Required"]})
        received_on = parse_date(d.get("received_on") or "")
        if not received_on:
            raise BusinessRuleError("Enter the date received.", fields={"received_on": ["Required"]})
        if received_on > timezone.localdate():
            raise BusinessRuleError("A receipt cannot be dated in the future.", fields={"received_on": ["In the future"]})
        evidence = (d.get("evidence_reference") or "").strip()
        if not evidence:
            raise BusinessRuleError("Add the evidence reference (bank ref, invoice no.).", fields={"evidence_reference": ["Required"]})
        client = access.clients_for(m).filter(pk=d.get("client_id")).first() if d.get("client_id") else None
        opp = access.opportunities_for(m).filter(pk=d.get("opportunity_id")).first() if d.get("opportunity_id") else None
        r = Receipt.objects.create(workspace=m.workspace, client=client, opportunity=opp, received_on=received_on, amount=amount,
                                   currency=currency, evidence_reference=evidence, note=(d.get("note") or "").strip(), recorded_by=m)
        audit.record(m.workspace, m, "receipt.created", r, f"Receipt {currency} {amount} recorded", {"evidence": evidence})
        return Response(ReceiptSerializer(r).data, status=201)


class CorrectionsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = CorrectionRequest.objects.filter(workspace=m.workspace).select_related("requested_by__user", "reviewed_by__user")
        if m.role in MANAGERS:
            qs = qs.filter(requested_by__in=access.team_members_visible(m)) | qs.filter(requested_by=m)
        else:
            qs = qs.filter(requested_by=m)
        return Response(CorrectionRequestSerializer(qs.distinct()[:200], many=True).data)

    def post(self, request):
        m = get_membership(request)
        d = request.data
        reason = (d.get("reason") or "").strip()
        if not reason:
            raise BusinessRuleError("Explain what is wrong.", fields={"reason": ["Required"]})
        entity_type = d.get("entity_type")
        if entity_type not in ("activity", "task", "alert"):
            raise BusinessRuleError("Corrections can be requested for activities, tasks and alerts.")
        cr = CorrectionRequest.objects.create(
            workspace=m.workspace, requested_by=m, entity_type=entity_type, entity_id=str(d.get("entity_id") or ""),
            field=(d.get("field") or "")[:60], current_value=d.get("current_value") or "", requested_value=d.get("requested_value") or "",
            reason=reason,
        )
        audit.record(m.workspace, m, "correction.requested", cr, f"Correction requested on {entity_type}")
        from modules.automation.engine import _managers_for, raise_alert

        raise_alert(m.workspace, "", _managers_for(m), "correction", cr.pk, f"Correction request from {m.display_name}",
                    reason, dedupe_key=f"correction:{cr.pk}", severity="info")
        return Response(CorrectionRequestSerializer(cr).data, status=201)


class CorrectionDecisionView(APIView):
    def post(self, request, pk):
        m = get_membership(request)
        require_role(m, *MANAGERS)
        cr = get_object_or_404(CorrectionRequest, workspace=m.workspace, pk=pk, requested_by__in=access.team_members_visible(m))
        decision = request.data.get("status")
        if decision not in ("approved", "rejected"):
            raise BusinessRuleError("Choose approve or reject.")
        if cr.requested_by_id == m.pk and m.role != Role.OWNER:
            raise BusinessRuleError("Another manager must review your own correction request.")
        note = (request.data.get("note") or "").strip()
        if decision == "approved" and cr.entity_type == "activity" and cr.field in ("occurred_at", "outcome", "subject", "body"):
            from modules.crm.models import Activity
            from modules.crm.services import edit_activity

            activity = Activity.objects.filter(workspace=m.workspace, pk=cr.entity_id).first()
            if activity:
                edit_activity(m, activity, {cr.field: cr.requested_value, "reason": f"Approved correction request: {cr.reason}"})
        cr.status = decision
        cr.review_note = note
        cr.reviewed_by = m
        cr.reviewed_at = timezone.now()
        cr.save()
        from modules.automation.engine import resolve_alerts

        resolve_alerts(m.workspace, f"correction:{cr.pk}", m, f"Correction {decision}")
        audit.record(m.workspace, m, "correction.decided", cr, f"Correction {decision}", {"note": note})
        return Response(CorrectionRequestSerializer(cr).data)


class WorkspaceExportView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, message="Only the owner can export the workspace.")
        data = services.workspace_export(m)
        audit.record(m.workspace, m, "export.workspace", ("workspace", m.workspace.pk), "Full workspace export downloaded")
        response = HttpResponse(json.dumps(data, indent=1, default=str), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="scalevexo-export-{timezone.now():%Y%m%d-%H%M}.json"'
        return response
