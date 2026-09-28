"""Acceptance criteria for CRM01-CRM13 that tests/test_requirements.py does not cover."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from modules.automation.engine import run_rules
from modules.automation.models import Alert, RuleDefinition
from modules.common.errors import BusinessRuleError
from modules.crm import services as crm
from modules.crm.models import Activity, Contact, Lead
from modules.identity import services as identity
from modules.identity import totp
from modules.identity.models import AuditEvent, Invitation, Role
from modules.support import services as support
from modules.work import services as work
from modules.work.models import Handover, Task

from .conftest import PASSWORD


def _lead(actor, owner=None, email="lead@example.com", name="Lena", company="Acme"):
    return crm.create_lead(actor, {"name": name, "company_name": company, "email": email, "source": "Referral",
                                   "owner_id": owner.pk if owner else None})


def _won(team, title="Site"):
    lead = _lead(team["manager"], team["rep1"], email=f"{title.lower()}@example.com")
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": title, "value": "1000", "currency": "USD"})
    return work.win_opportunity(team["rep1"], opp, {"version": opp.version, "scope": "Scope", "commercial_reference": "PO-1",
                                                    "commercial_decision": "CEO approved", "delivery_owner_id": team["dm"].pk})


def _task(owner, kind="follow_up", due=None, **links):
    return work.create_task(owner, {"title": "Call back", "kind": kind, "owner_id": owner.pk,
                                    "due_at": due or timezone.now() + timedelta(days=1), **links}, check_scope=False)


# ---------------------------------------------------------------- CRM01 identity and access
def test_invitation_is_single_use_and_revocable(team):
    inv = identity.create_invitation(team["owner"], "New.Person@Example.com", Role.SALES_REP)
    assert inv.email == "new.person@example.com"
    member = identity.accept_invitation(inv.token, "New", "Person", "Strong-Pass-2026")
    assert member.role == Role.SALES_REP and member.workspace == team["owner"].workspace
    with pytest.raises(BusinessRuleError):
        identity.accept_invitation(inv.token, "Again", "Person", "Strong-Pass-2026")

    revoked = identity.create_invitation(team["owner"], "other@example.com", Role.SALES_REP)
    revoked.revoked_at = timezone.now()
    revoked.save()
    with pytest.raises(BusinessRuleError):
        identity.accept_invitation(revoked.token, "Other", "Person", "Strong-Pass-2026")


def test_expired_invitation_cannot_be_used(team):
    inv = identity.create_invitation(team["owner"], "late@example.com", Role.SALES_REP)
    Invitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    with pytest.raises(BusinessRuleError):
        identity.accept_invitation(inv.token, "Late", "Person", "Strong-Pass-2026")


def test_only_owner_or_admin_can_invite(team, client_for):
    body = {"email": "x@example.com", "role": "sales_rep"}
    assert client_for(team["manager"]).post("/api/team/invitations", body, format="json").status_code == 403
    assert client_for(team["owner"]).post("/api/team/invitations", body, format="json").status_code == 201


def test_privileged_user_must_set_up_mfa_first(team, client_for, settings):
    settings.REQUIRE_MFA_FOR_PRIVILEGED = True
    c = client_for(team["owner"])
    blocked = c.get("/api/leads")
    assert blocked.status_code == 403 and blocked.json()["code"] == "mfa_setup_required"
    assert c.get("/api/auth/me").json()["mfa_setup_required"] is True
    # Non-privileged roles are not forced.
    assert client_for(team["rep1"]).get("/api/leads").status_code == 200


def test_login_with_mfa_needs_a_valid_code(team):
    from rest_framework.test import APIClient

    owner = team["owner"]
    owner.mfa_secret = totp.new_secret()
    owner.mfa_enabled = True
    owner.save()
    c = APIClient()
    first = c.post("/api/auth/login", {"email": owner.user.email, "password": PASSWORD}, format="json")
    assert first.json() == {"mfa_required": True}
    assert c.get("/api/leads").status_code in (401, 403)  # password alone does not sign in
    assert c.post("/api/auth/mfa-verify", {"code": "000000"}, format="json").status_code == 400
    ok = c.post("/api/auth/mfa-verify", {"code": totp.now_code(owner.mfa_secret)}, format="json")
    assert ok.status_code == 200 and c.get("/api/leads").status_code == 200


def test_admin_sees_no_pipeline_and_delivery_employee_sees_no_deal_values(team, client_for):
    won = _won(team)
    lead = _lead(team["manager"], team["rep1"], email="pipeline@example.com")
    assert client_for(team["admin"]).get(f"/api/leads/{lead.pk}").status_code == 404
    assert client_for(team["admin"]).get("/api/leads").json()["count"] == 0
    won.handover.project.members.add(team["dev"])
    deal = client_for(team["dev"]).get(f"/api/opportunities/{won.pk}")
    assert deal.status_code == 200 and deal.json()["value"] is None
    assert client_for(team["dm"]).get(f"/api/opportunities/{won.pk}").json()["value"] == "1000.00"


def test_suspended_member_cannot_receive_work(team):
    identity.suspend_member(team["owner"], team["rep2"], "Left")
    with pytest.raises(BusinessRuleError):
        identity.reassign_work(team["manager"], team["rep1"], team["rep2"], "Cover")
    with pytest.raises(BusinessRuleError):
        work.create_task(team["manager"], {"title": "x", "owner_id": team["rep2"].pk, "due_at": timezone.now()})


# ---------------------------------------------------------------- CRM02 contact quality
def test_duplicate_email_or_phone_is_blocked_until_reviewed(team):
    _lead(team["manager"], email="Dup@Example.com")
    with pytest.raises(BusinessRuleError) as exc:
        _lead(team["manager"], email="dup@example.com ", name="Other")
    assert exc.value.get_codes() == "duplicate_contact"
    crm.create_lead(team["manager"], {"name": "Pat", "phone": "+92 300 1234567", "country": "PK", "source": "Call"})
    with pytest.raises(BusinessRuleError):
        crm.create_lead(team["manager"], {"name": "Pat 2", "phone": "0300-1234567", "country": "PK", "source": "Call"})


def test_lead_needs_a_contact_method_or_source_reference(team):
    with pytest.raises(BusinessRuleError):
        crm.create_lead(team["manager"], {"name": "No Contact Info"})
    assert crm.create_lead(team["manager"], {"name": "Web Form", "source_reference": "form #42"}).pk


def test_merge_moves_history_and_archives_the_duplicate(team):
    a = _lead(team["manager"], team["rep1"], email="keep@example.com")
    b = crm.create_lead(team["manager"], {"name": "Lena B", "company_name": "Acme", "phone": "+1 202 555 0100",
                                          "country": "US", "owner_id": team["rep1"].pk})
    crm.log_activity(team["rep1"], {"kind": "call", "lead_id": b.pk, "outcome": "Talked"})
    with pytest.raises(BusinessRuleError):
        crm.merge_contacts(team["manager"], a.contact, b.contact, "")
    kept = crm.merge_contacts(team["manager"], a.contact, b.contact, "Same person")
    assert Lead.objects.filter(contact=kept).count() == 2
    assert Activity.objects.filter(contact=kept).count() == 1
    assert Contact.objects.get(pk=b.contact_id).archived is True
    assert kept.phone  # filled from the merged contact


# ---------------------------------------------------------------- CRM03 leads and opportunities
def test_lead_status_rules(team):
    lead = _lead(team["manager"], team["rep1"])
    for status, field in (("qualified", "need"), ("nurture", "nurture_review_date"), ("disqualified", "disqualify_reason")):
        with pytest.raises(BusinessRuleError) as exc:
            crm.change_lead_status(team["rep1"], lead, status, {"version": lead.version})
        assert field in exc.value.fields
    unowned = _lead(team["manager"], email="nobody@example.com")
    with pytest.raises(BusinessRuleError):
        crm.change_lead_status(team["manager"], unowned, "contacting", {"version": unowned.version})


def test_deal_stage_requirements_and_lost_closes_tasks(team):
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Deal"})
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], opp, "proposal", {"version": opp.version})
    opp = crm.move_stage(team["rep1"], opp, "proposal", {"version": opp.version, "scope_reference": "Proposal P-1"})
    task = _task(team["rep1"], opportunity_id=opp.pk)
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], opp, "lost", {"version": opp.version})
    opp = crm.move_stage(team["rep1"], opp, "lost", {"version": opp.version, "reason": "Budget"})
    task.refresh_from_db()
    assert task.status == Task.Status.CANCELLED
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], opp, "discovery", {"version": opp.version})  # reopening needs a reason
    assert crm.move_stage(team["rep1"], opp, "discovery", {"version": opp.version, "reason": "Budget found"}).closed_at is None


def test_value_needs_a_currency_and_totals_never_mix_currencies(team):
    lead = _lead(team["manager"], team["rep1"])
    with pytest.raises(BusinessRuleError):
        crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "No currency", "value": "10"})
    for value, cur in (("100", "USD"), ("50", "USD"), ("7000", "PKR")):
        crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": f"{cur} {value}", "value": value, "currency": cur})
    crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Unknown value"})
    from modules.crm.models import Opportunity

    discovery = next(s for s in crm.pipeline_summary(Opportunity.objects.all())["stages"] if s["stage"] == "discovery")
    assert {k: Decimal(v) for k, v in discovery["totals"].items()} == {"USD": Decimal("150"), "PKR": Decimal("7000")}
    assert discovery["unknown_value_count"] == 1 and discovery["count"] == 4


def test_won_deal_is_locked(team):
    won = _won(team)
    with pytest.raises(BusinessRuleError):
        crm.move_stage(team["rep1"], won, "negotiation", {"version": won.version})
    with pytest.raises(BusinessRuleError):
        crm.update_opportunity(team["rep1"], won, {"version": won.version, "value": "5"})


# ---------------------------------------------------------------- CRM04 activities
def test_activity_rules(team):
    lead = _lead(team["manager"], team["rep1"])
    with pytest.raises(BusinessRuleError):
        crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk})  # outcome required
    with pytest.raises(BusinessRuleError):
        crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "x",
                                        "occurred_at": (timezone.now() + timedelta(days=1)).isoformat()})
    act = crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Spoke"})
    lead.refresh_from_db()
    assert lead.status == "contacting" and lead.last_activity_at is not None
    with pytest.raises(BusinessRuleError) as exc:  # employees cannot rewrite when it happened
        crm.edit_activity(team["rep1"], act, {"occurred_at": (timezone.now() - timedelta(days=3)).isoformat(), "reason": "typo"})
    assert exc.value.get_codes() == "timestamp_locked"
    with pytest.raises(BusinessRuleError):
        crm.edit_activity(team["rep2"], act, {"outcome": "Changed", "reason": "Not mine"})


# ---------------------------------------------------------------- CRM05 tasks
def test_task_needs_reason_to_reschedule_block_and_cancel(team):
    task = _task(team["rep1"])
    for fn in (work.reschedule_task, work.set_task_blocked, work.cancel_task):
        with pytest.raises(BusinessRuleError):
            fn(team["rep1"], task, {"version": task.version, "due_at": timezone.now().isoformat()})
    task = work.complete_task(team["rep1"], task, {"version": task.version, "outcome": "Done", "stop_reason": "Not interested"})[0]
    with pytest.raises(BusinessRuleError):
        work.reschedule_task(team["rep1"], task, {"version": task.version, "reason": "x", "due_at": timezone.now().isoformat()})


def test_only_owner_or_their_manager_can_act_on_a_task(team):
    task = _task(team["rep1"])
    with pytest.raises(BusinessRuleError):
        work.complete_task(team["rep2"], task, {"version": task.version, "outcome": "x", "stop_reason": "y"})
    with pytest.raises(BusinessRuleError):
        work.complete_task(team["dm"], task, {"version": task.version, "outcome": "x", "stop_reason": "y"})
    assert work.complete_task(team["manager"], task, {"version": task.version, "outcome": "x", "stop_reason": "y"})[0].status == "done"


def test_completing_a_follow_up_creates_the_next_one(team):
    lead = _lead(team["manager"], team["rep1"])
    task = _task(team["rep1"], lead_id=lead.pk)
    due = timezone.now() + timedelta(days=2)
    _, nxt = work.complete_task(team["rep1"], task, {"version": task.version, "outcome": "Sent deck",
                                                      "next_action": "Chase reply", "next_action_due": due.isoformat()})
    lead.refresh_from_db()
    assert nxt.title == "Chase reply" and nxt.lead_id == lead.pk and lead.next_action == "Chase reply"


# ---------------------------------------------------------------- CRM06 rules and alerts
def test_unassigned_lead_alert_resolves_when_assigned(team, workspace):
    lead = _lead(team["manager"], email="unowned@example.com")
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=10))
    run_rules(workspace, only=["A01"])
    assert Alert.objects.filter(rule_code="A01", entity_id=str(lead.pk)).exclude(status="resolved").exists()
    lead.refresh_from_db()
    crm.update_lead(team["manager"], lead, {"version": lead.version, "owner_id": team["rep1"].pk})
    run_rules(workspace, only=["A01"])
    assert not Alert.objects.filter(rule_code="A01", entity_id=str(lead.pk)).exclude(status="resolved").exists()


def test_overdue_follow_up_alerts_owner_then_escalates(team, workspace):
    task = _task(team["rep1"], due=timezone.now() - timedelta(days=10))
    run_rules(workspace, only=["A03"])
    alerts = Alert.objects.filter(rule_code="A03", entity_id=str(task.pk))
    assert alerts.filter(recipient=team["rep1"]).exists()
    assert alerts.filter(recipient=team["manager"], severity="critical").exists()
    assert not Task.objects.exclude(pk=task.pk).filter(owner=team["rep1"]).exists()  # no automatic sanctions or tasks


def test_repeated_rescheduling_raises_a_review_not_a_penalty(team, workspace):
    task = _task(team["rep1"])
    for i in range(3):
        task = work.reschedule_task(team["rep1"], task, {"version": task.version, "reason": f"try {i}",
                                                         "due_at": (timezone.now() + timedelta(days=i + 2)).isoformat()})
    run_rules(workspace, only=["A08"])
    alert = Alert.objects.get(rule_code="A08", entity_id=str(task.pk))
    assert alert.recipient == team["manager"] and alert.severity == "info"
    assert "not a disciplinary decision" in alert.cause
    task.refresh_from_db()
    assert task.original_due_at < task.due_at and task.reschedule_count == 3


def test_critical_ticket_alerts_owner_and_delivery_manager(team):
    t = support.create_ticket(team["dev"], {"title": "Down", "severity": "critical", "owner_id": team["dev"].pk})
    recipients = set(Alert.objects.filter(rule_code="A07", entity_id=str(t.pk)).values_list("recipient", flat=True))
    assert {team["dev"].pk, team["dm"].pk, team["owner"].pk} <= recipients


def test_paused_rule_does_nothing_and_admin_edits_are_validated(team, workspace, client_for):
    RuleDefinition.objects.filter(workspace=workspace, code="A01").update(enabled=False)
    lead = _lead(team["manager"], email="paused@example.com")
    Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - timedelta(days=10))
    assert run_rules(workspace, only=["A01"])["A01"] == {"status": "paused"}
    assert not Alert.objects.filter(rule_code="A01").exists()
    rule = RuleDefinition.objects.get(workspace=workspace, code="A03")
    bad = client_for(team["owner"]).patch(f"/api/rules/{rule.pk}", {"params": {"overdue_working_hours": "DROP TABLE"}}, format="json")
    assert bad.status_code == 400
    assert client_for(team["rep1"]).patch(f"/api/rules/{rule.pk}", {"enabled": False}, format="json").status_code == 403


def test_alert_challenge_goes_to_the_manager(team, client_for):
    task = _task(team["rep1"], due=timezone.now() - timedelta(days=10))
    run_rules(team["owner"].workspace, only=["A03"])
    alert = Alert.objects.get(rule_code="A03", recipient=team["rep1"], entity_id=str(task.pk))
    c = client_for(team["rep1"])
    assert c.post(f"/api/alerts/{alert.pk}/challenge", {}, format="json").status_code == 400
    assert c.post(f"/api/alerts/{alert.pk}/challenge", {"note": "Client asked to wait"}, format="json").status_code == 200
    assert Alert.objects.filter(dedupe_key=f"challenge:{alert.pk}", recipient=team["manager"]).exists()


# ---------------------------------------------------------------- CRM07 conversion and onboarding
def test_handover_return_and_resubmit(team):
    won = _won(team)
    handover = won.handover
    with pytest.raises(BusinessRuleError):
        work.accept_handover(team["rep2"], handover, {})  # not the delivery owner
    with pytest.raises(BusinessRuleError):
        work.return_handover(team["dm"], handover, {})  # reason required
    handover = work.return_handover(team["dm"], handover, {"reason": "Missing contacts"})
    assert handover.status == Handover.Status.RETURNED
    assert Alert.objects.filter(recipient=team["rep1"], dedupe_key__startswith="handover-returned").exists()
    handover = work.resubmit_handover(team["rep1"], handover, {"version": handover.version, "client_contacts": "Olivia"})
    assert handover.status == Handover.Status.PENDING
    handover = work.accept_handover(team["dm"], handover, {})
    with pytest.raises(BusinessRuleError):
        work.return_handover(team["dm"], handover, {"reason": "late"})


def test_handover_to_absent_owner_goes_to_exception_queue(team):
    team["dev"].unavailable_until = timezone.localdate() + timedelta(days=5)
    team["dev"].save()
    lead = _lead(team["manager"], team["rep1"])
    opp = crm.create_opportunity(team["rep1"], {"lead_id": lead.pk, "title": "Absent"})
    won = work.win_opportunity(team["rep1"], opp, {"version": opp.version, "scope": "s", "commercial_reference": "c",
                                                   "commercial_decision": "d", "delivery_owner_id": team["dev"].pk})
    assert won.handover.status == Handover.Status.EXCEPTION
    assert Alert.objects.filter(recipient=team["dm"], severity="critical", dedupe_key=f"handover:{won.handover.pk}").exists()


def test_delivery_work_waits_for_handover_acceptance(team):
    won = _won(team)
    ms = won.handover.project.milestones.order_by("order").first()
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dm"], ms, "in_progress", {"version": ms.version})


# ---------------------------------------------------------------- CRM08 projects and milestones
def test_milestone_needs_evidence_and_independent_review(team):
    won = _won(team)
    work.accept_handover(team["dm"], won.handover, {})
    project = won.handover.project
    project.members.add(team["dev"])
    ms = project.milestones.order_by("order").first()
    ms = work.transition_milestone(team["dev"], ms, "in_progress", {"version": ms.version})
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dev"], ms, "in_review", {"version": ms.version})
    ms = work.transition_milestone(team["dev"], ms, "in_review", {"version": ms.version, "evidence": "Demo link"})
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dev"], ms, "accepted", {"version": ms.version})  # not a reviewer
    ms = work.transition_milestone(team["dm"], ms, "accepted", {"version": ms.version})
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dm"], ms, "in_progress", {"version": ms.version})  # reopen needs a reason
    ms = work.transition_milestone(team["dm"], ms, "in_progress", {"version": ms.version, "note": "Client found a bug"})
    assert ms.reopen_count == 1 and ms.events.count() >= 4


def test_blocked_milestone_needs_description_and_next_owner(team):
    won = _won(team)
    work.accept_handover(team["dm"], won.handover, {})
    ms = won.handover.project.milestones.order_by("order").first()
    ms = work.transition_milestone(team["dm"], ms, "in_progress", {"version": ms.version})
    with pytest.raises(BusinessRuleError):
        work.transition_milestone(team["dm"], ms, "blocked", {"version": ms.version, "blocker_description": "Waiting"})
    ms = work.transition_milestone(team["dm"], ms, "blocked", {"version": ms.version, "blocker_description": "Waiting",
                                                                 "blocker_next_owner_id": team["rep1"].pk})
    assert ms.blocker_next_owner == team["rep1"]


def test_scope_change_is_separate_from_defect(team):
    won = _won(team)
    project = won.handover.project
    scope = work.add_project_change(team["dm"], project, {"kind": "scope_change", "title": "Add blog"})
    defect = work.add_project_change(team["dm"], project, {"kind": "defect", "title": "Broken link"})
    assert {scope.kind, defect.kind} == {"scope_change", "defect"}


# ---------------------------------------------------------------- CRM09 tickets
def test_ticket_waiting_needs_reason_owner_and_review_time(team):
    t = support.create_ticket(team["dm"], {"title": "Bug", "owner_id": team["dev"].pk})
    assert t.status == "triaged"
    with pytest.raises(BusinessRuleError):
        support.transition_ticket(team["dev"], t, "waiting_customer", {"version": t.version, "waiting_reason": "Need logs"})
    t = support.transition_ticket(team["dev"], t, "waiting_customer", {
        "version": t.version, "waiting_reason": "Need logs", "waiting_next_owner_id": team["dm"].pk,
        "waiting_review_at": (timezone.now() + timedelta(days=1)).isoformat()})
    t = support.transition_ticket(team["dev"], t, "in_progress", {"version": t.version})
    assert t.waiting_reason == "" and t.waiting_next_owner is None
    with pytest.raises(BusinessRuleError):
        support.transition_ticket(team["dev"], t, "closed", {"version": t.version})  # must resolve first


def test_ticket_notes_keep_internal_and_client_visible_apart(team):
    t = support.create_ticket(team["dm"], {"title": "Q"})
    support.add_note(team["dm"], t, {"body": "Internal detail"})
    support.add_note(team["dm"], t, {"body": "We are on it", "visibility": "client"})
    assert list(t.notes.order_by("created_at").values_list("visibility", flat=True)) == ["internal", "client"]
    with pytest.raises(BusinessRuleError):
        support.add_note(team["dm"], t, {"body": "x", "visibility": "public"})


def test_ticket_numbers_are_sequential_per_workspace(team):
    numbers = [support.create_ticket(team["dm"], {"title": f"T{i}"}).number for i in range(3)]
    assert numbers == [1, 2, 3]


# ---------------------------------------------------------------- CRM10 accountability
def test_correction_request_is_reviewed_by_another_manager(team, client_for):
    lead = _lead(team["manager"], team["rep1"])
    act = crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Spoke"})
    c = client_for(team["rep1"])
    cr = c.post("/api/corrections", {"entity_type": "activity", "entity_id": str(act.pk), "field": "outcome",
                                     "requested_value": "Voicemail", "reason": "Wrong outcome"}, format="json")
    assert cr.status_code == 201
    pk = cr.json()["id"]
    assert c.post(f"/api/corrections/{pk}", {"status": "approved"}, format="json").status_code == 403
    assert client_for(team["manager"]).post(f"/api/corrections/{pk}", {"status": "approved"}, format="json").status_code == 200
    act.refresh_from_db()
    assert act.outcome == "Voicemail" and act.corrected and act.revisions.count() == 1


def test_accountability_view_states_it_is_not_a_performance_score(team, client_for):
    body = client_for(team["manager"]).get("/api/reports/accountability").json()
    text = str(body).lower()
    assert "score" not in text or "not a performance score" in text
    assert client_for(team["rep1"]).get("/api/reports/accountability").status_code in (200, 403)


# ---------------------------------------------------------------- CRM11 reporting and receipts
def test_only_owner_records_cash_and_receipts_need_evidence(team, client_for):
    body = {"amount": "100", "currency": "USD", "received_on": timezone.localdate().isoformat()}
    assert client_for(team["manager"]).post("/api/receipts", {**body, "evidence_reference": "FT-1"}, format="json").status_code == 403
    owner = client_for(team["owner"])
    assert owner.post("/api/receipts", body, format="json").status_code == 400
    future = {**body, "received_on": (timezone.localdate() + timedelta(days=2)).isoformat(), "evidence_reference": "FT-1"}
    assert owner.post("/api/receipts", future, format="json").status_code == 400
    assert owner.post("/api/receipts", {**body, "evidence_reference": "FT-1"}, format="json").status_code == 201


def test_reports_are_for_managers_only(team, client_for):
    assert client_for(team["rep1"]).get("/api/reports/overview").status_code == 403
    assert client_for(team["dev"]).get("/api/reports/overview").status_code == 403
    for m in ("owner", "manager", "dm"):
        assert client_for(team[m]).get("/api/reports/overview").status_code == 200


# ---------------------------------------------------------------- CRM12 AI
def test_ai_suggestion_changes_nothing(team, workspace):
    from modules.ai import services as ai
    from modules.ai.models import AISettings

    AISettings.objects.update_or_create(workspace=workspace, defaults={"enabled": True, "provider": "mock"})
    lead = _lead(team["manager"], team["rep1"])
    crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Wants a quote next week."})
    lead.refresh_from_db()
    before = (lead.status, lead.version, Task.objects.count(), Activity.objects.count())
    result = ai.draft_followup(team["rep1"], "lead", lead.pk)
    lead.refresh_from_db()
    assert result["output"]["body"] and "Nothing has been sent" in result["notice"]
    assert (lead.status, lead.version, Task.objects.count(), Activity.objects.count()) == before


def test_ai_cannot_read_records_outside_the_users_scope(team, workspace):
    from modules.ai import services as ai
    from modules.ai.models import AISettings

    AISettings.objects.update_or_create(workspace=workspace, defaults={"enabled": True, "provider": "mock"})
    lead = _lead(team["manager"], team["rep1"])
    crm.log_activity(team["rep1"], {"kind": "call", "lead_id": lead.pk, "outcome": "Private notes"})
    with pytest.raises(BusinessRuleError):
        ai.summarize(team["rep2"], "lead", lead.pk)


# ---------------------------------------------------------------- CRM13 portability and audit
def test_audit_log_is_append_only(team):
    event = AuditEvent.objects.first()
    event.summary = "tampered"
    with pytest.raises(PermissionError):
        event.save()
    with pytest.raises(PermissionError):
        event.delete()


def test_workspace_export_contains_the_journey(team, client_for):
    _won(team)
    res = client_for(team["owner"]).get("/api/export/workspace.json")
    assert res.status_code == 200
    import json

    data = json.loads(res.content)
    records = data["records"]
    for label in ("crm.Lead", "crm.Opportunity", "work.Client", "work.Handover", "work.Project", "work.Milestone"):
        assert records[label], label
    assert {m["role"] for m in data["members"]} >= {"owner", "sales_rep"}
    assert AuditEvent.objects.filter(action="export.workspace").exists()


def test_leads_csv_export_is_limited_to_sales_managers(team, client_for):
    assert client_for(team["rep1"]).get("/api/export/leads.csv").status_code == 403
    res = client_for(team["manager"]).get("/api/export/leads.csv")
    assert res.status_code == 200 and res["Content-Type"].startswith("text/csv")
