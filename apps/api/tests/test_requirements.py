"""Acceptance tests mapped to TEST01-TEST14 in the product brief."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from modules.ai import services as ai
from modules.ai.models import AISettings
from modules.automation.engine import run_rules
from modules.automation.models import Alert
from modules.common.errors import BusinessRuleError, ConflictError
from modules.crm import services as crm
from modules.crm.models import Lead
from modules.support import services as support
from modules.work import services as work
from modules.work.models import Client, Handover, Project, Task


def _lead(actor, owner=None, email="a@example.com", name="Alice"):
    return crm.create_lead(actor, {"name": name, "company_name": "Acme", "email": email, "source": "LinkedIn",
                                   "owner_id": owner.pk if owner else None})


# TEST01 / TEST02 - identity, authorisation and isolation
def test_rep_cannot_read_other_reps_lead(team, client_for):
    lead = _lead(team["manager"], team["rep1"])
    other = client_for(team["rep2"])
    assert other.get(f"/api/leads/{lead.pk}").status_code == 404
    assert client_for(team["rep1"]).get(f"/api/leads/{lead.pk}").status_code == 200


def test_suspended_user_session_is_rejected(team, client_for):
    from modules.identity.services import suspend_member

    c = client_for(team["rep1"])
    assert c.get("/api/auth/me").status_code == 200
    suspend_member(team["owner"], team["rep1"], "Left the company")
    assert c.get("/api/auth/me").status_code in (401, 403)


def test_reassignment_requires_reason_and_keeps_author(team):
    from modules.identity.services import reassign_work

    lead = _lead(team["manager"], team["rep1"])
    act = crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Spoke"})
    with pytest.raises(BusinessRuleError):
        reassign_work(team["manager"], team["rep1"], team["rep2"], "")
    reassign_work(team["manager"], team["rep1"], team["rep2"], "Holiday cover")
    lead.refresh_from_db()
    act.refresh_from_db()
    assert lead.owner == team["rep2"] and act.author == team["rep1"]


# TEST03 - import
def test_import_counts_reconcile_and_retry_is_idempotent(team):
    rows = ["Name,Company,Email,Phone,Source"]
    for i in range(1000):
        rows.append(f"Person {i},Co {i},p{i}@example.com,,Import")
    rows.append("Dup,Co,p1@example.com,,Import")      # duplicate inside file
    rows.append("Bad,Co,not-an-email,,Import")         # invalid
    rows.append(",,,,")                                 # blank
    csv_text = "\n".join(rows)
    batch, existing = crm.import_preview(team["manager"], "leads.csv", csv_text)
    assert not existing
    mapping = {"Name": "name", "Company": "company_name", "Email": "email", "Phone": "phone", "Source": "source"}
    batch = crm.import_confirm(team["manager"], batch, mapping)
    c = batch.counts
    assert c["created"] == 1000 and c["duplicates"] == 1 and c["invalid"] == 1 and c["skipped_blank"] == 1
    assert c["created"] + c["duplicates"] + c["invalid"] + c["skipped_blank"] == c["total_rows"]
    again, existing = crm.import_preview(team["manager"], "leads.csv", csv_text)
    assert existing and again.pk == batch.pk
    crm.import_confirm(team["manager"], again, mapping)
    assert Lead.objects.filter(import_batch=batch).count() == 1000


def test_csv_export_neutralises_formulas():
    from modules.common.csvsafe import write_csv

    assert "'=HYPERLINK" in write_csv(["a"], [["=HYPERLINK(\"x\")"]])


# TEST04 - pipeline
def test_stale_update_is_rejected(team):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site", "value": "100", "currency": "USD"})
    crm.update_opportunity(team["rep1"], opp, {"version": opp.version, "title": "Site v2"})
    with pytest.raises(ConflictError):
        crm.update_opportunity(team["rep1"], opp, {"version": opp.version, "title": "Stale"})


def test_won_requires_evidence_and_unknown_value_stays_unknown(team):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site"})
    assert opp.value is None
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], opp, "won", {"version": opp.version})
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], opp, "lost", {"version": opp.version})
    summary = crm.pipeline_summary([opp])
    assert summary["stages"][0]["unknown_value_count"] == 1


# TEST05 - activities
def test_manual_activity_is_self_reported_and_edit_leaves_trail(team):
    lead = _lead(team["manager"], team["rep1"])
    a = crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Call completed", "verification": "provider_confirmed"})
    assert a.verification == "self_reported"
    crm.edit_activity(team["rep1"], a, {"outcome": "Voicemail", "reason": "Typo"})
    assert a.revisions.count() == 1 and a.corrected


# TEST06 - tasks
def test_reschedule_keeps_original_deadline_and_completion_needs_next_step(team):
    t = work.create_task(team["rep1"], {"title": "Call", "kind": "follow_up", "due_at": timezone.now() + timedelta(hours=1)})
    original = t.original_due_at
    t = work.reschedule_task(team["rep1"], t, {"version": t.version, "reason": "Client asked", "due_at": (timezone.now() + timedelta(days=1)).isoformat()})
    assert t.original_due_at == original and t.reschedule_count == 1
    with pytest.raises(BusinessRuleError):
        work.complete_task(team["rep1"], t, {"version": t.version, "outcome": "Done"})
    t, nxt = work.complete_task(team["rep1"], t, {"version": t.version, "outcome": "Done", "stop_reason": "Not interested"})
    assert t.status == "done" and nxt is None


# TEST07 - rules
def test_rule_run_twice_creates_one_alert_and_pause_stops_it(team, workspace):
    lead = _lead(team["manager"], None)
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=5))
    run_rules(workspace)
    run_rules(workspace)
    assert Alert.objects.filter(rule_code="A01", entity_id=str(lead.pk), recipient=team["manager"]).count() == 1
    # assigning the lead clears the alert automatically
    lead.refresh_from_db()
    crm.update_lead(team["manager"], lead, {"version": lead.version, "owner_id": team["rep1"].pk})
    run_rules(workspace)
    assert not Alert.objects.filter(rule_code="A01", entity_id=str(lead.pk)).exclude(status="resolved").exists()


# TEST08 - conversion
def test_win_creates_one_client_and_project_even_on_retry(team):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site", "value": "500", "currency": "USD"})
    data = {"version": opp.version, "scope": "5 pages", "commercial_reference": "PO-1", "commercial_decision": "CEO approved",
            "delivery_owner_id": team["dm"].pk}
    work.win_opportunity(team["rep1"], opp, data)
    work.win_opportunity(team["rep1"], opp, data)
    assert Client.objects.count() == 1 and Project.objects.count() == 1 and Handover.objects.count() == 1


# TEST09 - milestones
def test_dependency_blocks_acceptance_without_override(team):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site"})
    opp = work.win_opportunity(team["rep1"], opp, {"version": opp.version, "scope": "x", "commercial_reference": "y",
                                                   "commercial_decision": "z", "delivery_owner_id": team["dm"].pk})
    work.accept_handover(team["dm"], opp.handover, {})
    ms = list(opp.handover.project.milestones.order_by("order"))
    second = ms[1]
    second = work.transition_milestone(team["dm"], second, "in_progress", {"version": second.version})
    second = work.transition_milestone(team["dm"], second, "in_review", {"version": second.version, "evidence": "link"})
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dm"], second, "accepted", {"version": second.version})
    second = work.transition_milestone(team["dm"], second, "accepted", {"version": second.version, "override_reason": "Client waived"})
    assert second.status == "accepted" and second.override_reason


# TEST10 - tickets
def test_ticket_resolution_requires_evidence_and_reopen_keeps_history(team):
    t = support.create_ticket(team["dev"], {"title": "Bug", "owner_id": team["dev"].pk, "severity": "critical"})
    assert Alert.objects.filter(rule_code="A07", entity_id=str(t.pk)).exists()
    t = support.transition_ticket(team["dev"], t, "in_progress", {"version": t.version})
    with pytest.raises(BusinessRuleError):
        support.transition_ticket(team["dev"], t, "resolved", {"version": t.version})
    t = support.transition_ticket(team["dev"], t, "resolved", {"version": t.version, "resolution_note": "Fixed", "closure_test_result": "Passed"})
    t = support.transition_ticket(team["dev"], t, "triaged", {"version": t.version, "note": "Came back"})
    assert t.reopen_count == 1 and t.events.filter(snapshot__resolution_note="Fixed").exists()


# TEST12 - reporting
def test_won_deal_does_not_count_as_cash(team, client_for):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site", "value": "500", "currency": "USD"})
    work.win_opportunity(team["rep1"], opp, {"version": opp.version, "scope": "x", "commercial_reference": "y",
                                             "commercial_decision": "z", "delivery_owner_id": team["dm"].pk})
    data = client_for(team["owner"]).get("/api/reports/overview").json()
    assert data["sections"]["won"]["by_currency"]["USD"]["total"] == "500.00"
    assert data["sections"]["receipts"]["by_currency"] == {}


# TEST13 - AI
def test_ai_disabled_and_budget_limit(team, workspace):
    lead = _lead(team["manager"], team["rep1"])
    crm.log_activity(team["rep1"], {"kind": "note", "lead_id": lead.pk, "body": "Wants a new site by March."})
    with pytest.raises(ai.AIDisabled):
        ai.summarize(team["rep1"], "lead", lead.pk)
    s = AISettings.objects.get(workspace=workspace)
    s.enabled, s.provider = True, "mock"
    s.save()
    out = ai.summarize(team["rep1"], "lead", lead.pk)
    assert out["output"]["summary"] and out["sources"]
    s.provider, s.monthly_budget_usd = "anthropic", Decimal("0.001")
    s.save()
    assert ai.reserve(workspace, s, Decimal("0.0008")) is True
    assert ai.reserve(workspace, s, Decimal("0.0008")) is False  # second concurrent reservation cannot overspend


# TEST14 - export
def test_only_owner_can_export(team, client_for):
    assert client_for(team["rep1"]).get("/api/export/workspace.json").status_code == 403
    r = client_for(team["owner"]).get("/api/export/workspace.json")
    assert r.status_code == 200 and b"scalevexo-crm-export" in r.content


def test_rules_create_task_for_deal_without_next_action(team, workspace):
    lead = _lead(team["manager"], team["rep1"])
    crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Site"})
    run_rules(workspace)
    run_rules(workspace)
    assert Task.objects.filter(created_by_rule="A02").count() == 1
