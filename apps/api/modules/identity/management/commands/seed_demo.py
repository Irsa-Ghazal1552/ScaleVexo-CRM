"""Synthetic demo data so every screen can be tried before real data is imported.

Everything created here is fictional. Remove it with:  python manage.py seed_demo --remove
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from modules.identity.models import Membership, Role, Workspace

User = get_user_model()
DEMO_DOMAIN = "demo.scalevexo.local"
DEMO_PASSWORD = "DemoPass!2026"  # noqa: S105 - published demo login, removed with --remove

PEOPLE = [
    ("sara", "Sara", "Khan", Role.SALES_MANAGER, "Sales Manager"),
    ("rabia", "Rabia", "Muneeb", Role.SALES_REP, "Business Development Representative"),
    ("ali", "Ali", "Raza", Role.SALES_REP, "Business Development Representative"),
    ("hamza", "Hamza", "Iqbal", Role.DELIVERY_MANAGER, "Delivery Manager"),
    ("zainab", "Zainab", "Shah", Role.DELIVERY_EMPLOYEE, "Full-stack Developer"),
    ("usman", "Usman", "Tariq", Role.ADMIN, "Workspace Administrator"),
]

LEADS = [
    ("Olivia Carter", "Brightpath Dental Group", "olivia@brightpath-demo.com", "LinkedIn", "rabia", "contacting"),
    ("James Miller", "Northwind Realty", "james@northwind-demo.com", "Website form", "rabia", "qualified"),
    ("Ayesha Siddiqui", "Karachi Threads", "ayesha@karachithreads-demo.pk", "Referral", "ali", "assigned"),
    ("Daniel Brooks", "Summit Legal LLP", "daniel@summitlegal-demo.com", "Cold email", "ali", "contacting"),
    ("Priya Nair", "Lotus Wellness Spa", "priya@lotuswellness-demo.com", "LinkedIn", "rabia", "nurture"),
    ("Mark Evans", "Evans Auto Repair", "mark@evansauto-demo.com", "Google Ads", None, "new"),
    ("Fatima Noor", "Noor Interiors", "fatima@noorinteriors-demo.pk", "Instagram", None, "new"),
    ("Chris Walker", "Walker Logistics", "chris@walkerlogistics-demo.com", "Event", "ali", "qualified"),
    ("Hina Aslam", "Aslam Medical Center", "hina@aslammedical-demo.pk", "Referral", "rabia", "qualified"),
    ("Tom Richards", "Richards Plumbing", "tom@richardsplumbing-demo.com", "Website form", "ali", "disqualified"),
]


class Command(BaseCommand):
    help = "Load fictional demo data (or remove it with --remove)."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true")

    def handle(self, *args, **o):
        ws = Workspace.objects.first()
        if ws is None:
            raise CommandError("Run bootstrap_workspace first.")
        if o["remove"]:
            self._remove(ws)
            return
        from modules.crm.models import Contact

        # --remove keeps the (deactivated) demo users, so look for the demo records instead.
        if Contact.objects.filter(workspace=ws, email__contains="-demo.").exists():
            self.stdout.write("Demo data already loaded.")
            return
        with transaction.atomic():
            self._seed(ws)
        self.stdout.write(self.style.SUCCESS(
            f"Demo data loaded. Demo logins: sara@{DEMO_DOMAIN}, rabia@{DEMO_DOMAIN}, hamza@{DEMO_DOMAIN} ... password {DEMO_PASSWORD}"))

    def _remove(self, ws):
        from modules.crm.models import Contact
        from modules.work.models import Client

        with transaction.atomic():
            demo_contacts = Contact.objects.filter(workspace=ws, email__contains="-demo.")
            from modules.ai.models import AIRequest
            from modules.automation.models import Alert, RuleExecution
            from modules.crm.models import Activity, ImportBatch, Lead, Opportunity, StageHistory
            from modules.reporting.models import CorrectionRequest, Receipt
            from modules.support.models import Ticket
            from modules.work.models import Handover, Project, Task

            clients = Client.objects.filter(workspace=ws, primary_contact__in=demo_contacts)
            Receipt.objects.filter(client__in=clients).delete()
            Ticket.objects.filter(client__in=clients).delete()
            Task.objects.filter(workspace=ws, owner__user__email__endswith="@" + DEMO_DOMAIN).delete()
            Project.objects.filter(client__in=clients).delete()
            opps = Opportunity.objects.filter(contact__in=demo_contacts)
            Handover.objects.filter(opportunity__in=opps).delete()
            clients.delete()
            Activity.objects.filter(contact__in=demo_contacts).delete()
            StageHistory.objects.filter(workspace=ws, entity_id__in=list(opps.values_list("id", flat=True)) + list(Lead.objects.filter(contact__in=demo_contacts).values_list("id", flat=True))).delete()
            opps.delete()
            Lead.objects.filter(contact__in=demo_contacts).delete()
            demo_contacts.delete()
            Alert.objects.filter(recipient__user__email__endswith="@" + DEMO_DOMAIN).delete()
            CorrectionRequest.objects.filter(requested_by__user__email__endswith="@" + DEMO_DOMAIN).delete()
            AIRequest.objects.filter(requested_by__user__email__endswith="@" + DEMO_DOMAIN).delete()
            Membership.objects.filter(user__email__endswith="@" + DEMO_DOMAIN).update(status="suspended")
            User.objects.filter(email__endswith="@" + DEMO_DOMAIN).update(is_active=False)
            _ = (RuleExecution, ImportBatch)
        self.stdout.write(self.style.SUCCESS("Demo records removed and demo users deactivated (audit history is kept)."))

    def _seed(self, ws):
        from modules.ai.models import AISettings
        from modules.automation.engine import run_rules
        from modules.crm import services as crm
        from modules.crm.models import Lead
        from modules.reporting.models import Receipt
        from modules.support import services as support
        from modules.work import services as work
        from modules.work.models import Milestone, Task

        owner = Membership.objects.filter(workspace=ws, role=Role.OWNER).first()
        people = {}
        for key, first, last, role, title in PEOPLE:
            # Reuses the users an earlier --remove deactivated.
            user, _ = User.objects.get_or_create(username=f"{key}@{DEMO_DOMAIN}", defaults={
                "email": f"{key}@{DEMO_DOMAIN}", "first_name": first, "last_name": last})
            user.is_active = True
            user.set_password(DEMO_PASSWORD)
            user.save()
            people[key], _ = Membership.objects.update_or_create(workspace=ws, user=user, defaults={
                "role": role, "title": title, "status": Membership.Status.ACTIVE, "suspended_at": None, "suspended_reason": ""})
        mgr = people["sara"]
        now = timezone.now()

        leads = {}
        for name, company, email, source, owner_key, status in LEADS:
            lead = crm.create_lead(mgr, {"name": name, "company_name": company, "email": email, "source": source,
                                          "owner_id": people[owner_key].pk if owner_key else None})
            Lead.objects.filter(pk=lead.pk).update(created_at=now - timedelta(days=12))
            lead.refresh_from_db()
            if status in ("qualified",):
                lead.need, lead.fit = "New website with online booking", "We build booking-enabled sites for service businesses"
                lead.save()
                lead = crm.change_lead_status(mgr, lead, "qualified", {"version": lead.version})
            elif status == "nurture":
                lead = crm.change_lead_status(mgr, lead, "nurture", {"version": lead.version, "nurture_review_date": (now + timedelta(days=30)).date().isoformat()})
            elif status == "disqualified":
                lead = crm.change_lead_status(mgr, lead, "disqualified", {"version": lead.version, "disqualify_reason": "Budget below minimum project size"})
            leads[company] = lead

        def act(member, lead, kind, outcome, body, days_ago, opp=None):
            a = crm.log_activity(member, {"kind": kind, "lead_id": lead.pk if not opp else None, "opportunity_id": opp.pk if opp else None,
                                          "outcome": outcome, "body": body, "occurred_at": (now - timedelta(days=days_ago)).isoformat()})
            return a

        rabia, ali, hamza, zainab = people["rabia"], people["ali"], people["hamza"], people["zainab"]
        act(rabia, leads["Brightpath Dental Group"], "linkedin", "Connection accepted", "Sent intro about SEO + booking site. Olivia replied she is reviewing vendors.", 6)
        act(ali, leads["Summit Legal LLP"], "email", "No reply yet", "Cold email about AI intake chatbot for law firms.", 9)

        o1 = crm.create_opportunity(rabia, {"lead_id": leads["Northwind Realty"].pk, "title": "Northwind - property listing website", "service": "Web development",
                                            "value": "4800", "currency": "USD", "next_action": "Send proposal", "next_action_due": (now + timedelta(days=1)).isoformat()})
        act(rabia, None, "meeting", "Discovery call done", "James wants listings synced from their CRM, lead forms, and SEO for 3 cities. Decision by end of month. Budget approved internally.", 3, opp=o1)
        o1 = crm.move_stage(rabia, o1, "qualified", {"version": o1.version})

        o2 = crm.create_opportunity(ali, {"lead_id": leads["Walker Logistics"].pk, "title": "Walker - AI dispatch assistant", "service": "AI solutions",
                                          "value": "12000", "currency": "USD"})
        o2 = crm.move_stage(ali, o2, "qualified", {"version": o2.version})
        o2 = crm.move_stage(ali, o2, "proposal", {"version": o2.version, "scope_reference": "Proposal SVX-P-0142 (Drive link)"})
        act(ali, None, "call", "Proposal walkthrough", "Chris liked the dispatch assistant demo. Concerned about integration with their TMS. Asked for a phased plan.", 5, opp=o2)

        o3 = crm.create_opportunity(rabia, {"lead_id": leads["Aslam Medical Center"].pk, "title": "Aslam Medical - patient portal + SEO", "service": "Web + SEO",
                                            "value": "950000", "currency": "PKR", "next_action": "Negotiate payment milestones", "next_action_due": (now - timedelta(hours=30)).isoformat()})
        o3 = crm.move_stage(rabia, o3, "proposal", {"version": o3.version, "scope_reference": "Proposal SVX-P-0150"})
        o3 = crm.move_stage(rabia, o3, "negotiation", {"version": o3.version})

        o4 = crm.create_opportunity(ali, {"contact_id": leads["Karachi Threads"].contact_id, "title": "Karachi Threads - Shopify store", "service": "E-commerce",
                                          "value": "350000", "currency": "PKR"})
        o4.refresh_from_db()
        o4 = crm.move_stage(ali, o4, "lost", {"version": o4.version, "reason": "Chose a cheaper freelancer"})

        o5 = crm.create_opportunity(rabia, {"contact_id": leads["Brightpath Dental Group"].contact_id, "title": "Brightpath - booking website + local SEO",
                                            "service": "Web + SEO", "value": "6500", "currency": "USD"})
        o5 = crm.move_stage(rabia, o5, "proposal", {"version": o5.version, "scope_reference": "Proposal SVX-P-0138"})
        o5 = work.win_opportunity(rabia, o5, {
            "version": o5.version, "scope": "5-page website, online booking (3 clinics), Google Business Profile setup, local SEO for 3 months.",
            "exclusions": "Content writing beyond 5 pages; paid ads.", "client_contacts": "Olivia Carter (owner) olivia@brightpath-demo.com",
            "commercial_reference": "Signed proposal SVX-P-0138, 50% advance", "commercial_decision": "Approved by CEO; 50/50 payment terms",
            "delivery_owner_id": hamza.pk, "promised_start": now.date().isoformat(), "promised_end": (now + timedelta(days=35)).date().isoformat(),
        })
        handover = o5.handover
        work.accept_handover(hamza, handover, {})
        project = handover.project
        project.members.add(zainab)
        ms = list(project.milestones.order_by("order"))
        ms[0].owner = zainab
        ms[0].save()
        m0 = work.transition_milestone(zainab, ms[0], "in_progress", {"version": ms[0].version})
        m0 = work.transition_milestone(zainab, m0, "in_review", {"version": m0.version, "evidence": "Kick-off notes + access checklist (Drive)"})
        work.transition_milestone(hamza, m0, "accepted", {"version": m0.version})
        m1 = Milestone.objects.get(pk=ms[1].pk)
        m1 = work.transition_milestone(hamza, m1, "in_progress", {"version": m1.version})
        work.transition_milestone(hamza, m1, "blocked", {"version": m1.version, "blocker_description": "Waiting for clinic opening hours and doctor list from client",
                                                          "blocker_next_owner_id": rabia.pk})
        Receipt.objects.create(workspace=ws, client=handover.client, opportunity=o5, received_on=now.date(), amount="3250", currency="USD",
                               evidence_reference="Bank ref FT-2291 (advance 50%)", recorded_by=owner)

        support.create_ticket(zainab, {"title": "Booking form not sending confirmation email", "client_id": handover.client.pk, "project_id": project.pk,
                                       "severity": "critical", "owner_id": zainab.pk, "description": "Client reports patients get no confirmation."})
        support.create_ticket(hamza, {"title": "Add Urdu language toggle", "client_id": handover.client.pk, "project_id": project.pk, "severity": "low"})

        t = work.create_task(ali, {"title": "Call Daniel about intake chatbot", "kind": "follow_up", "owner_id": ali.pk,
                                   "due_at": now - timedelta(days=2), "lead_id": leads["Summit Legal LLP"].pk}, check_scope=False)
        Task.objects.filter(pk=t.pk).update(original_due_at=now - timedelta(days=4))
        work.create_task(rabia, {"title": "Send revised proposal to Olivia's partner clinic", "kind": "follow_up", "owner_id": rabia.pk,
                                 "due_at": now + timedelta(hours=3), "lead_id": leads["Brightpath Dental Group"].pk}, check_scope=False)

        ai, _ = AISettings.objects.get_or_create(workspace=ws)
        ai.enabled, ai.provider = True, AISettings.Provider.MOCK
        ai.save()
        run_rules(ws)
