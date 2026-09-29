from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from modules.ai import views as ai
from modules.automation import views as automation
from modules.crm import views as crm
from modules.identity import views as identity
from modules.reporting import views as reporting
from modules.support import views as support
from modules.work import views as work


def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


api = [
    path("health", health),
    # identity (CRM01)
    path("auth/csrf", identity.CsrfView.as_view()),
    path("auth/login", identity.LoginView.as_view()),
    path("auth/mfa-verify", identity.MfaVerifyView.as_view()),
    path("auth/logout", identity.LogoutView.as_view()),
    path("auth/me", identity.MeView.as_view()),
    path("auth/mfa/setup", identity.MfaSetupView.as_view()),
    path("auth/mfa/enable", identity.MfaEnableView.as_view()),
    path("auth/password", identity.PasswordChangeView.as_view()),
    path("invitations/<str:token>", identity.InvitationPublicView.as_view()),
    path("team/members", identity.MembersView.as_view()),
    path("team/members/<uuid:pk>", identity.MemberDetailView.as_view()),
    path("team/members/<uuid:pk>/<str:action>", identity.MemberActionView.as_view()),
    path("team/invitations", identity.InvitationsView.as_view()),
    path("team/invitations/<uuid:pk>/revoke", identity.InvitationRevokeView.as_view()),
    path("settings/workspace", identity.WorkspaceSettingsView.as_view()),
    path("audit", identity.AuditLogView.as_view()),
    # CRM (CRM02-CRM04)
    path("contacts", crm.ContactsView.as_view()),
    path("contacts/check-duplicates", crm.ContactDuplicateCheckView.as_view()),
    path("contacts/merge", crm.ContactMergeView.as_view()),
    path("contacts/<uuid:pk>", crm.ContactDetailView.as_view()),
    path("leads", crm.LeadsView.as_view()),
    path("leads/<uuid:pk>", crm.LeadDetailView.as_view()),
    path("leads/<uuid:pk>/<str:action>", crm.LeadActionView.as_view()),
    path("opportunities", crm.OpportunitiesView.as_view()),
    path("opportunities/pipeline", crm.PipelineView.as_view()),
    path("opportunities/<uuid:pk>", crm.OpportunityDetailView.as_view()),
    path("opportunities/<uuid:pk>/stage", crm.OpportunityStageView.as_view()),
    path("activities", crm.ActivitiesView.as_view()),
    path("activities/<uuid:pk>", crm.ActivityDetailView.as_view()),
    path("imports", crm.ImportsView.as_view()),
    path("imports/<uuid:pk>", crm.ImportDetailView.as_view()),
    path("imports/<uuid:pk>/confirm", crm.ImportConfirmView.as_view()),
    path("imports/<uuid:pk>/errors.csv", crm.ImportErrorsView.as_view()),
    path("export/leads.csv", crm.LeadsExportView.as_view()),
    # work (CRM05, CRM07, CRM08)
    path("today", work.TodayView.as_view()),
    path("tasks", work.TasksView.as_view()),
    path("tasks/<uuid:pk>/<str:action>", work.TaskActionView.as_view()),
    path("clients", work.ClientsView.as_view()),
    path("clients/<uuid:pk>", work.ClientDetailView.as_view()),
    path("handovers", work.HandoversView.as_view()),
    path("handovers/<uuid:pk>", work.HandoverActionView.as_view()),
    path("handovers/<uuid:pk>/<str:action>", work.HandoverActionView.as_view()),
    path("projects", work.ProjectsView.as_view()),
    path("projects/<uuid:pk>", work.ProjectDetailView.as_view()),
    path("projects/<uuid:pk>/<str:action>", work.ProjectActionView.as_view()),
    path("milestones/<uuid:pk>", work.MilestoneView.as_view()),
    path("project-changes/<uuid:pk>", work.ProjectChangeView.as_view()),
    path("templates", work.TemplatesView.as_view()),
    path("templates/<uuid:pk>", work.TemplateDetailView.as_view()),
    # support (CRM09)
    path("tickets", support.TicketsView.as_view()),
    path("tickets/<uuid:pk>", support.TicketDetailView.as_view()),
    path("tickets/<uuid:pk>/<str:action>", support.TicketActionView.as_view()),
    # automation (CRM06)
    path("alerts", automation.AlertsView.as_view()),
    path("alerts/count", automation.AlertCountView.as_view()),
    path("alerts/<uuid:pk>/<str:action>", automation.AlertActionView.as_view()),
    path("rules", automation.RulesView.as_view()),
    path("rules/run", automation.RunRulesView.as_view()),
    path("rules/executions", automation.RuleExecutionsView.as_view()),
    path("rules/<uuid:pk>", automation.RuleDetailView.as_view()),
    path("cron/rules", automation.CronRulesView.as_view()),
    # reporting (CRM10, CRM11, CRM13)
    path("reports/overview", reporting.OverviewView.as_view()),
    path("reports/accountability", reporting.AccountabilityView.as_view()),
    path("reports/<str:name>", reporting.ReportView.as_view()),
    path("receipts", reporting.ReceiptsView.as_view()),
    path("corrections", reporting.CorrectionsView.as_view()),
    path("corrections/<uuid:pk>", reporting.CorrectionDecisionView.as_view()),
    path("export/workspace.json", reporting.WorkspaceExportView.as_view()),
    # AI (CRM12)
    path("ai/summarize", ai.AISummarizeView.as_view()),
    path("ai/draft-followup", ai.AIDraftView.as_view()),
    path("ai/requests/<uuid:pk>/decision", ai.AIDecisionView.as_view()),
    path("ai/settings", ai.AISettingsView.as_view()),
    path("ai/history", ai.AIHistoryView.as_view()),
]

urlpatterns = [path("api/", include(api)), path("django-admin/", admin.site.urls)]
