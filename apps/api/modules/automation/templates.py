"""Approved rule templates A01–A08 from the Product and Delivery Brief, section 5.

Administrators can edit timing and recipients (params) and pause a rule, but
cannot add arbitrary code, SQL or URLs.
"""

RULE_TEMPLATES = [
    {
        "code": "A01",
        "name": "Unassigned new lead",
        "trigger": "A new lead has no owner.",
        "conditions": "The lead is still unassigned after the configured number of working minutes.",
        "action": "Alert the sales managers. Only one unresolved alert is kept per lead.",
        "explanation": "New leads cool quickly; a manager must give every lead an owner.",
        "params": {"working_minutes": 30, "recipient_role": "sales_manager"},
    },
    {
        "code": "A02",
        "name": "Opportunity without a next action",
        "trigger": "An open opportunity has no next action in the future.",
        "conditions": "Stage is Discovery, Qualified, Proposal or Negotiation and next action due is empty or in the past.",
        "action": "Create a task for the owner and show the deal in the manager exception view.",
        "explanation": "Every open deal needs a dated next step.",
        "params": {"task_due_working_hours": 4, "recipient_role": "sales_manager"},
    },
    {
        "code": "A03",
        "name": "Overdue follow-up",
        "trigger": "A follow-up task passes its due time.",
        "conditions": "The task is still open after the configured working hours; escalation after the configured working days.",
        "action": "Notify the task owner; escalate to their manager if still overdue.",
        "explanation": "Missed follow-ups are the most common way deals are lost.",
        "params": {"overdue_working_hours": 2, "escalate_after_working_days": 1},
    },
    {
        "code": "A04",
        "name": "Quiet open deal",
        "trigger": "No meaningful activity on an open deal.",
        "conditions": "No activity recorded for the configured number of working days.",
        "action": "Request an update from the owner. The deal is never marked lost automatically.",
        "explanation": "Silence usually means a deal is slipping.",
        "params": {"quiet_working_days": 3},
    },
    {
        "code": "A05",
        "name": "Deal won - start onboarding",
        "trigger": "A deal becomes Won.",
        "conditions": "Accepted scope, commercial decision and delivery owner are recorded.",
        "action": "Create onboarding exactly once and request delivery acceptance.",
        "explanation": "Delivery must receive what sales promised.",
        "params": {},
    },
    {
        "code": "A06",
        "name": "Milestone at risk",
        "trigger": "A milestone is overdue or one of its dependencies is blocked.",
        "conditions": "Milestone not accepted or cancelled.",
        "action": "Notify the delivery manager with the affected commitment.",
        "explanation": "Delivery risks must surface before the client notices.",
        "params": {"recipient_role": "delivery_manager"},
    },
    {
        "code": "A07",
        "name": "Critical ticket",
        "trigger": "A critical ticket is created or raised to critical.",
        "conditions": "Severity is critical.",
        "action": "Notify the incident owner and the fallback owner.",
        "explanation": "Critical client issues need an immediate owner.",
        "params": {"incident_owner_id": None, "fallback_role": "owner"},
    },
    {
        "code": "A08",
        "name": "Repeated rescheduling",
        "trigger": "A task is rescheduled several times.",
        "conditions": "Rescheduled at least the configured number of times within the window.",
        "action": "Raise a reviewable exception for the manager. This is not a disciplinary decision.",
        "explanation": "Repeated rescheduling can signal a blocked or unclear task.",
        "params": {"count": 3, "window_days": 7},
    },
]

TEMPLATE_BY_CODE = {t["code"]: t for t in RULE_TEMPLATES}

# Allowed parameter types for validation of admin edits.
PARAM_TYPES = {
    "working_minutes": int,
    "task_due_working_hours": int,
    "overdue_working_hours": int,
    "escalate_after_working_days": int,
    "quiet_working_days": int,
    "count": int,
    "window_days": int,
    "recipient_role": str,
    "fallback_role": str,
    "incident_owner_id": (str, type(None)),
}
