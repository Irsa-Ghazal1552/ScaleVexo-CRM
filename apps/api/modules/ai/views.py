from decimal import Decimal, InvalidOperation

from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import audit
from modules.common.errors import BusinessRuleError
from modules.identity.auth import CONFIG, get_membership, require_role
from modules.identity.models import Role

from . import services
from .models import AIRequest, AISettings


class AISummarizeView(APIView):
    def post(self, request):
        m = get_membership(request)
        d = request.data
        return Response(services.summarize(m, d.get("entity_type"), d.get("entity_id"), d.get("activity_ids") or []))


class AIDraftView(APIView):
    def post(self, request):
        m = get_membership(request)
        if m.role not in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP, Role.DELIVERY_MANAGER):
            raise BusinessRuleError("Drafting follow-ups is available to sales and delivery managers.")
        d = request.data
        return Response(services.draft_followup(m, d.get("entity_type"), d.get("entity_id"), d.get("activity_ids") or [], d.get("instructions") or ""))


class AIDecisionView(APIView):
    def post(self, request, pk):
        m = get_membership(request)
        req = services.record_decision(m, pk, request.data.get("decision"))
        return Response({"id": str(req.pk), "user_decision": req.user_decision})


class AISettingsView(APIView):
    def get(self, request):
        m = get_membership(request)
        s = services.get_settings(m.workspace)
        data = {
            "enabled": s.enabled, "provider": s.provider, "model": s.model, "monthly_budget_usd": str(s.monthly_budget_usd),
            "input_cost_per_mtok": str(s.input_cost_per_mtok), "output_cost_per_mtok": str(s.output_cost_per_mtok),
            "max_output_tokens": s.max_output_tokens, "providers": [{"value": v, "label": l} for v, l in AISettings.Provider.choices],
            "usage": services.usage(m.workspace),
        }
        return Response(data)

    def patch(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        s = services.get_settings(m.workspace)
        d = request.data
        changes = {}
        if "enabled" in d:
            s.enabled = bool(d["enabled"])
            changes["enabled"] = s.enabled
        if "provider" in d:
            if d["provider"] not in AISettings.Provider.values:
                raise BusinessRuleError("Unknown provider.")
            s.provider = d["provider"]
            changes["provider"] = s.provider
        if "model" in d:
            s.model = (d["model"] or "").strip()[:80] or s.model
            changes["model"] = s.model
        for f in ("monthly_budget_usd", "input_cost_per_mtok", "output_cost_per_mtok"):
            if f in d:
                if f == "monthly_budget_usd" and m.role != Role.OWNER:
                    raise BusinessRuleError("Only the owner can change the AI budget.")
                try:
                    value = Decimal(str(d[f]))
                except InvalidOperation:
                    raise BusinessRuleError(f"{f} must be a number.")
                if value < 0 or value > 1000:
                    raise BusinessRuleError(f"{f} is out of range.")
                setattr(s, f, value)
                changes[f] = str(value)
        if "max_output_tokens" in d:
            s.max_output_tokens = max(100, min(4000, int(d["max_output_tokens"])))
        s.save()
        audit.record(m.workspace, m, "ai.settings", ("workspace", m.workspace.pk), "AI settings updated", changes)
        return self.get(request)


class AIHistoryView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        rows = AIRequest.objects.filter(workspace=m.workspace).select_related("requested_by__user")[:100]
        return Response([
            {"id": str(r.pk), "feature": r.feature, "status": r.status, "provider": r.provider, "cost_usd": str(r.cost_usd),
             "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "user_decision": r.user_decision, "error": r.error,
             "requested_by": r.requested_by.display_name if r.requested_by else None, "created_at": r.created_at}
            for r in rows
        ])
