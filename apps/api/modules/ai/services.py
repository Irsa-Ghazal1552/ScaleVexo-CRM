"""Selective AI assistance (CRM12).

* Summaries and drafts are grounded only in notes the user is allowed to see.
* Output is a suggestion: nothing is sent, no stage is changed, no price promised.
* The organisation-wide monthly limit is enforced with a row lock, so parallel
  requests cannot overspend it.
* When AI is disabled, over budget or unavailable, the rest of the CRM keeps working.
"""
import re
from decimal import Decimal

from django.conf import settings as django_settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException

from modules.common import access, audit
from modules.common.errors import BusinessRuleError

from . import providers
from .models import AIBudgetMonth, AIRequest, AISettings


class AIUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "ai_unavailable"
    default_detail = "AI assistance is unavailable right now. You can continue working normally."


class AIDisabled(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "ai_disabled"
    default_detail = "AI assistance is turned off for this workspace."


class AIOverBudget(APIException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "ai_budget_exceeded"
    default_detail = "The monthly AI budget has been reached. AI features resume next month or when an owner raises the limit."


SYSTEM_PROMPT = (
    "You assist sales and delivery staff at ScaleVexo, a web development and AI solutions agency. "
    "Use ONLY the notes provided. Do not invent facts, prices, discounts, deadlines or contractual terms. "
    "Never assess employee performance or misconduct. If the notes do not support something, leave it out. "
    "Reply with a single JSON object and nothing else."
)


def month_key(now=None):
    return (now or timezone.now()).strftime("%Y-%m")


def get_settings(workspace):
    obj, _ = AISettings.objects.get_or_create(workspace=workspace)
    return obj


def _cost(ai, input_tokens, output_tokens):
    if ai.provider == AISettings.Provider.MOCK:
        return Decimal("0")
    return (Decimal(input_tokens) * ai.input_cost_per_mtok + Decimal(output_tokens) * ai.output_cost_per_mtok) / Decimal(1_000_000)


def reserve(workspace, ai, estimate):
    AIBudgetMonth.objects.get_or_create(workspace=workspace, month=month_key())
    with transaction.atomic():
        row = AIBudgetMonth.objects.select_for_update().get(workspace=workspace, month=month_key())
        if row.spent_usd + row.reserved_usd + estimate > ai.monthly_budget_usd:
            return False
        row.reserved_usd += estimate
        row.save(update_fields=["reserved_usd"])
    return True


def settle(workspace, estimate, actual):
    with transaction.atomic():
        row = AIBudgetMonth.objects.select_for_update().get(workspace=workspace, month=month_key())
        row.reserved_usd = max(Decimal("0"), row.reserved_usd - estimate)
        row.spent_usd += actual
        row.request_count += 1
        row.save(update_fields=["reserved_usd", "spent_usd", "request_count"])


def usage(workspace):
    ai = get_settings(workspace)
    row = AIBudgetMonth.objects.filter(workspace=workspace, month=month_key()).first()
    spent = row.spent_usd if row else Decimal("0")
    return {
        "month": month_key(),
        "enabled": ai.enabled,
        "provider": ai.provider,
        "model": ai.model,
        "budget_usd": str(ai.monthly_budget_usd),
        "spent_usd": str(spent.quantize(Decimal("0.0001"))),
        "reserved_usd": str((row.reserved_usd if row else Decimal("0")).quantize(Decimal("0.0001"))),
        "remaining_usd": str(max(Decimal("0"), ai.monthly_budget_usd - spent).quantize(Decimal("0.0001"))),
        "requests": row.request_count if row else 0,
        "api_key_configured": bool(django_settings.AI_ANTHROPIC_API_KEY),
    }


def _load_entity(actor, entity_type, entity_id):
    scopes = {"lead": access.leads_for, "opportunity": access.opportunities_for, "client": access.clients_for}
    if entity_type not in scopes:
        raise BusinessRuleError("AI works on leads, deals and clients.")
    obj = scopes[entity_type](actor).filter(pk=entity_id).first()
    if obj is None:
        raise BusinessRuleError("Record not found.")
    return obj


def _notes(actor, entity_type, obj, activity_ids):
    qs = access.activities_for(actor).filter(**{entity_type: obj}).order_by("-occurred_at")
    if activity_ids:
        qs = qs.filter(pk__in=activity_ids)
    items = []
    for a in qs[:20]:
        text = " ".join(x for x in (a.subject, a.outcome, a.body) if x).strip()
        if text:
            items.append({"id": str(a.pk), "kind": a.kind, "date": a.occurred_at.strftime("%Y-%m-%d"), "text": text[:2000]})
    if not items:
        raise BusinessRuleError("Select at least one note or activity with text for the AI to use.", code="ai_no_sources")
    return items


def _context(actor, entity_type, obj):
    contact = obj.primary_contact if entity_type == "client" else obj.contact
    name = contact.label
    topic = getattr(obj, "title", "") or getattr(obj, "service", "") or getattr(obj, "name", "") or "your project"
    return {
        "name": name,
        "contact_first_name": (contact.name or "").split(" ")[0],
        "topic": topic,
        "sender_name": actor.display_name,
    }


def _run(actor, feature, entity_type, entity_id, activity_ids, build_prompt, validate):
    ws = actor.workspace
    ai = get_settings(ws)
    obj = _load_entity(actor, entity_type, entity_id)
    notes = _notes(actor, entity_type, obj, activity_ids or [])
    context = _context(actor, entity_type, obj)
    base = dict(workspace=ws, requested_by=actor, feature=feature, entity_type=entity_type, entity_id=str(obj.pk),
                source_activity_ids=[n["id"] for n in notes], provider=ai.provider, model=ai.model)
    if not ai.enabled:
        AIRequest.objects.create(status=AIRequest.Status.DISABLED, **base)
        raise AIDisabled()
    prompt = build_prompt(notes, context)
    est_in = (len(SYSTEM_PROMPT) + len(prompt)) // 3 + 50
    estimate = _cost(ai, est_in, ai.max_output_tokens)
    if not reserve(ws, ai, estimate):
        AIRequest.objects.create(status=AIRequest.Status.OVER_BUDGET, **base)
        raise AIOverBudget()
    tokens_in = tokens_out = 0
    try:
        if ai.provider == AISettings.Provider.MOCK:
            output, tokens_in, tokens_out = providers.mock_complete(feature, notes, context)
        else:
            text, tokens_in, tokens_out = providers.anthropic_complete(ai, SYSTEM_PROMPT, prompt)
            output = providers.extract_json(text)
        output = validate(output, {n["id"] for n in notes})
    except providers.ProviderError as exc:
        settle(ws, estimate, _cost(ai, tokens_in, tokens_out))
        AIRequest.objects.create(status=AIRequest.Status.FAILED, error=str(exc)[:500], input_tokens=tokens_in, output_tokens=tokens_out, **base)
        raise AIUnavailable(detail=f"AI assistance is unavailable right now ({exc}). You can continue working normally.")
    actual = _cost(ai, tokens_in, tokens_out)
    settle(ws, estimate, actual)
    req = AIRequest.objects.create(status=AIRequest.Status.OK, input_tokens=tokens_in, output_tokens=tokens_out,
                                   cost_usd=actual, output=output, **base)
    audit.record(ws, actor, f"ai.{feature}", (entity_type, obj.pk), f"AI {feature.replace('_', ' ')} generated", {"request": str(req.pk)})
    return {
        "request_id": str(req.pk),
        "feature": feature,
        "provider": ai.provider,
        "output": output,
        "sources": [{"id": n["id"], "kind": n["kind"], "date": n["date"], "text": n["text"]} for n in notes if n["id"] in output.get("source_ids", [])] or notes,
        "cost_usd": str(actual.quantize(Decimal("0.000001"))),
        "notice": "AI suggestion. Review, edit or reject it. Nothing has been sent or changed.",
    }


def _notes_block(notes):
    return "\n".join(f"[{n['id']}] {n['date']} {n['kind']}: {n['text']}" for n in notes)


def summarize(actor, entity_type, entity_id, activity_ids=None):
    def build(notes, ctx):
        return (
            f"Summarise these CRM notes about {ctx['name']}.\n\nNOTES:\n{_notes_block(notes)}\n\n"
            'Return JSON: {"summary": "2-4 sentences", "key_points": ["..."], "open_questions": ["..."], '
            '"source_ids": ["ids of the notes you used"]}'
        )

    def validate(out, allowed):
        summary = str(out.get("summary") or "").strip()
        if not summary:
            raise providers.ProviderError("The AI returned an empty summary.")
        return {
            "summary": summary[:2000],
            "key_points": [str(x)[:400] for x in (out.get("key_points") or [])][:10],
            "open_questions": [str(x)[:400] for x in (out.get("open_questions") or [])][:6],
            "source_ids": [s for s in (out.get("source_ids") or []) if s in allowed],
        }

    return _run(actor, AIRequest.Feature.SUMMARIZE, entity_type, entity_id, activity_ids, build, validate)


PRICE_RE = re.compile(r"(\$|USD|PKR|EUR|GBP|AED|Rs\.?)\s?\d|\d+\s?(USD|PKR|EUR|GBP|AED|dollars|rupees)", re.I)


def draft_followup(actor, entity_type, entity_id, activity_ids=None, instructions=""):
    instructions = (instructions or "").strip()[:500]

    def build(notes, ctx):
        return (
            f"Draft a short, friendly follow-up email from {ctx['sender_name']} to {ctx['name']} about '{ctx['topic']}'.\n"
            f"Extra instructions from the user: {instructions or 'none'}\n\nNOTES:\n{_notes_block(notes)}\n\n"
            "Do not mention prices, discounts or deadlines unless they appear in the notes. "
            'Return JSON: {"subject": "...", "body": "...", "source_ids": ["ids of notes used"]}'
        )

    def validate(out, allowed):
        subject = str(out.get("subject") or "").strip()
        body = str(out.get("body") or "").strip()
        if not body:
            raise providers.ProviderError("The AI returned an empty draft.")
        warnings = []
        if PRICE_RE.search(body):
            warnings.append("The draft mentions an amount. Check it against the approved proposal before sending.")
        return {"subject": subject[:200], "body": body[:5000], "source_ids": [s for s in (out.get("source_ids") or []) if s in allowed], "warnings": warnings}

    return _run(actor, AIRequest.Feature.DRAFT_FOLLOWUP, entity_type, entity_id, activity_ids, build, validate)


def record_decision(actor, request_id, decision):
    if decision not in ("accepted", "edited", "rejected"):
        raise BusinessRuleError("Decision must be accepted, edited or rejected.")
    req = AIRequest.objects.filter(workspace=actor.workspace, pk=request_id, requested_by=actor).first()
    if req is None:
        raise BusinessRuleError("AI request not found.")
    req.user_decision = decision
    req.save(update_fields=["user_decision", "updated_at"])
    return req
