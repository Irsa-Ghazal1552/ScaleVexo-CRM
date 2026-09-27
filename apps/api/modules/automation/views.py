from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import access, audit
from modules.common.errors import BusinessRuleError
from modules.identity.auth import CONFIG, get_membership, require_role
from modules.identity.models import Membership, Role

from .engine import run_rules
from .models import Alert, RuleDefinition, RuleExecution, WorkerHeartbeat
from .serializers import AlertSerializer, RuleExecutionSerializer, RuleSerializer
from .templates import PARAM_TYPES, TEMPLATE_BY_CODE


class AlertsView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = Alert.objects.filter(workspace=m.workspace).select_related("recipient__user", "resolved_by__user")
        scope = request.query_params.get("scope", "mine")
        if scope == "team" and m.role in (Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER):
            qs = qs.filter(recipient__in=access.team_members_visible(m))
        else:
            qs = qs.filter(recipient=m)
        status = request.query_params.get("status", "open")
        if status == "open":
            qs = qs.exclude(status="resolved")
        elif status != "all":
            qs = qs.filter(status=status)
        if request.query_params.get("rule"):
            qs = qs.filter(rule_code=request.query_params["rule"])
        from modules.crm.views import paginate

        return paginate(self, request, qs, AlertSerializer)


class AlertCountView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = Alert.objects.filter(workspace=m.workspace, recipient=m).exclude(status="resolved")
        return Response({"open": qs.count(), "critical": qs.filter(severity="critical").count()})


class AlertActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        alert = get_object_or_404(Alert, workspace=m.workspace, pk=pk)
        is_recipient = alert.recipient_id == m.pk
        is_manager = access.team_members_visible(m).filter(pk=alert.recipient_id).exists() and m.role in (
            Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER)
        if not (is_recipient or is_manager):
            raise BusinessRuleError("You cannot act on this alert.")
        if action == "acknowledge":
            alert.status = Alert.Status.ACKNOWLEDGED
            alert.acknowledged_at = timezone.now()
        elif action == "resolve":
            note = (request.data.get("note") or "").strip()
            if not note:
                raise BusinessRuleError("Add a short resolution note.", fields={"note": ["Required"]})
            alert.status = Alert.Status.RESOLVED
            alert.resolved_at = timezone.now()
            alert.resolved_by = m
            alert.resolution_note = note
        elif action == "challenge":
            note = (request.data.get("note") or "").strip()
            if not note:
                raise BusinessRuleError("Explain why this alert is not right.", fields={"note": ["Required"]})
            alert.challenge_note = note
            # Let the recipient's manager review the challenge.
            from .engine import _managers_for, raise_alert

            raise_alert(m.workspace, alert.rule_code, _managers_for(alert.recipient), alert.entity_type, alert.entity_id,
                        f"Alert challenged by {alert.recipient.display_name}: {alert.title}", note,
                        dedupe_key=f"challenge:{alert.pk}", severity="info")
        else:
            raise BusinessRuleError("Unknown action.")
        alert.save()
        audit.record(m.workspace, m, f"alert.{action}", alert, f"Alert {action}: {alert.title}")
        return Response(AlertSerializer(alert).data)


class RulesView(APIView):
    def get(self, request):
        m = get_membership(request)
        hb = WorkerHeartbeat.objects.filter(name="rules").first()
        return Response({
            "rules": RuleSerializer(RuleDefinition.objects.filter(workspace=m.workspace), many=True).data,
            "worker": {"last_run_at": hb.last_run_at if hb else None,
                       "last_result": (hb.last_result or {}).get(str(m.workspace.pk)) if hb else None},
            "members": [{"id": str(x.pk), "name": x.display_name, "role": x.role}
                        for x in Membership.objects.filter(workspace=m.workspace, status="active")],
        })


class RuleDetailView(APIView):
    def patch(self, request, pk):
        m = get_membership(request)
        require_role(m, *CONFIG)
        rule = get_object_or_404(RuleDefinition, workspace=m.workspace, pk=pk)
        changes = {}
        if "enabled" in request.data:
            rule.enabled = bool(request.data["enabled"])
            changes["enabled"] = rule.enabled
        if "params" in request.data:
            params = request.data["params"] or {}
            allowed = TEMPLATE_BY_CODE[rule.code]["params"].keys()
            clean = dict(rule.params)
            for k, v in params.items():
                if k not in allowed:
                    raise BusinessRuleError(f"'{k}' is not an editable setting for {rule.code}.")
                expected = PARAM_TYPES.get(k, str)
                if expected is int:
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        raise BusinessRuleError(f"'{k}' must be a whole number.")
                    if v < 0 or v > 10000:
                        raise BusinessRuleError(f"'{k}' is out of range.")
                elif k.endswith("_role"):
                    if v not in Role.values:
                        raise BusinessRuleError(f"'{k}' must be a valid role.")
                elif k == "incident_owner_id" and v:
                    if not Membership.objects.filter(workspace=m.workspace, pk=v).exists():
                        raise BusinessRuleError("Incident owner not found.")
                clean[k] = v or (None if k == "incident_owner_id" else v)
            changes["params"] = {"from": rule.params, "to": clean}
            rule.params = clean
        rule.version += 1
        rule.updated_by = m
        rule.save()
        audit.record(m.workspace, m, "rule.updated", rule, f"Rule {rule.code} updated (v{rule.version})", changes)
        return Response(RuleSerializer(rule).data)


class RunRulesView(APIView):
    def post(self, request):
        m = get_membership(request)
        require_role(m, Role.OWNER, Role.ADMIN, Role.SALES_MANAGER, Role.DELIVERY_MANAGER)
        result = run_rules(m.workspace)
        audit.record(m.workspace, m, "rules.run", ("workspace", m.workspace.pk), "Rules evaluated manually", result)
        return Response(result)


class RuleExecutionsView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        return Response(RuleExecutionSerializer(RuleExecution.objects.filter(workspace=m.workspace)[:200], many=True).data)
