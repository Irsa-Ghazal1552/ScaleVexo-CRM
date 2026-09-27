from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.middleware.csrf import get_token
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.common import audit
from modules.common.errors import BusinessRuleError

from . import services, totp
from .auth import CONFIG, MANAGERS, get_membership, membership_for, mfa_setup_pending, require_role
from .models import AuditEvent, Invitation, Membership, Role
from .serializers import AuditEventSerializer, InvitationSerializer, MemberSerializer, WorkspaceSerializer

User = get_user_model()


def me_payload(membership):
    from modules.common.access import can_see_commercials

    ws = membership.workspace
    return {
        "user": {
            "id": membership.user.pk,
            "email": membership.user.email,
            "first_name": membership.user.first_name,
            "last_name": membership.user.last_name,
        },
        "membership": MemberSerializer(membership).data,
        "workspace": WorkspaceSerializer(ws).data,
        "mfa_setup_required": mfa_setup_pending(membership),
        "capabilities": {
            "sales": membership.role in (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP),
            "sales_manage": membership.role in (Role.OWNER, Role.SALES_MANAGER),
            "delivery": membership.role in (Role.OWNER, Role.DELIVERY_MANAGER, Role.DELIVERY_EMPLOYEE, Role.SALES_MANAGER),
            "delivery_manage": membership.role in (Role.OWNER, Role.DELIVERY_MANAGER),
            "manager": membership.role in MANAGERS,
            "configure": membership.role in CONFIG,
            "commercials": can_see_commercials(membership),
            "receipts": membership.role == Role.OWNER,
            "export": membership.role == Role.OWNER,
            "reports": membership.role in MANAGERS,
        },
        "roles": [{"value": v, "label": l} for v, l in Role.choices],
    }


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            enforce_csrf(request)


def enforce_csrf(request):
    """Same CSRF check DRF applies to session-authenticated requests."""
    from django.middleware.csrf import CsrfViewMiddleware
    from rest_framework.exceptions import PermissionDenied

    def dummy_get_response(req):
        return None

    check = CsrfViewMiddleware(dummy_get_response)
    check.process_request(request._request)
    reason = check.process_view(request._request, None, (), {})
    if reason:
        raise PermissionDenied("CSRF check failed. Reload the page and try again.")


class CsrfView(PublicView):
    def get(self, request):
        get_token(request._request)
        return Response({"ok": True})


class LoginView(PublicView):
    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        password = request.data.get("password") or ""
        user = authenticate(request._request, username=email, password=password)
        if user is None:
            raise BusinessRuleError("Email or password is incorrect.", code="invalid_credentials")
        membership = membership_for(user)
        if membership is None or not membership.is_active:
            raise BusinessRuleError("Your access to this workspace is suspended.", code="suspended")
        if membership.mfa_enabled:
            request.session["mfa_pending_user"] = user.pk
            return Response({"mfa_required": True})
        login(request._request, user)
        audit.record(membership.workspace, membership, "auth.login", membership, f"{membership.display_name} signed in")
        return Response(me_payload(membership))


class MfaVerifyView(PublicView):
    def post(self, request):
        user_id = request.session.get("mfa_pending_user")
        if not user_id:
            raise BusinessRuleError("Sign in with your password first.", code="mfa_no_pending")
        user = get_object_or_404(User, pk=user_id)
        membership = membership_for(user)
        if not membership or not membership.is_active or not totp.verify(membership.mfa_secret, request.data.get("code")):
            raise BusinessRuleError("The verification code is not valid.", code="mfa_invalid")
        request.session.pop("mfa_pending_user", None)
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        audit.record(membership.workspace, membership, "auth.login", membership, f"{membership.display_name} signed in with MFA")
        return Response(me_payload(membership))


class LogoutView(APIView):
    allow_without_mfa = True

    def post(self, request):
        logout(request._request)
        return Response({"ok": True})


class MeView(APIView):
    allow_without_mfa = True

    def get(self, request):
        return Response(me_payload(get_membership(request)))


class MfaSetupView(APIView):
    allow_without_mfa = True

    def post(self, request):
        m = get_membership(request)
        secret = totp.new_secret()
        request.session["mfa_setup_secret"] = secret
        return Response({"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, m.user.email)})


class MfaEnableView(APIView):
    allow_without_mfa = True

    def post(self, request):
        m = get_membership(request)
        secret = request.session.get("mfa_setup_secret")
        if not secret or not totp.verify(secret, request.data.get("code")):
            raise BusinessRuleError("The code does not match. Check your authenticator app and try again.", code="mfa_invalid")
        m.mfa_secret = secret
        m.mfa_enabled = True
        m.save(update_fields=["mfa_secret", "mfa_enabled"])
        request.session.pop("mfa_setup_secret", None)
        audit.record(m.workspace, m, "auth.mfa_enabled", m, f"{m.display_name} enabled MFA")
        return Response(me_payload(m))


class PasswordChangeView(APIView):
    allow_without_mfa = True

    def post(self, request):
        m = get_membership(request)
        if not m.user.check_password(request.data.get("current_password") or ""):
            raise BusinessRuleError("Your current password is incorrect.")
        new = request.data.get("new_password") or ""
        try:
            validate_password(new, m.user)
        except DjangoValidationError as exc:
            raise BusinessRuleError(" ".join(exc.messages))
        m.user.set_password(new)
        m.user.save()
        update_session_auth_hash(request._request, m.user)
        audit.record(m.workspace, m, "auth.password_changed", m, f"{m.display_name} changed their password")
        return Response({"ok": True})


class InvitationPublicView(PublicView):
    def get(self, request, token):
        inv = Invitation.objects.select_related("workspace").filter(token=token).first()
        if inv is None or not inv.is_usable:
            raise BusinessRuleError("This invitation link is invalid or has expired.", code="invalid_invitation")
        return Response({"email": inv.email, "role": inv.get_role_display(), "workspace": inv.workspace.name})

    def post(self, request, token):
        password = request.data.get("password") or ""
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            raise BusinessRuleError(" ".join(exc.messages))
        first = (request.data.get("first_name") or "").strip()
        if not first:
            raise BusinessRuleError("Please enter your first name.")
        membership = services.accept_invitation(token, first, (request.data.get("last_name") or "").strip(), password)
        login(request._request, membership.user, backend="django.contrib.auth.backends.ModelBackend")
        return Response(me_payload(membership))


class MembersView(APIView):
    def get(self, request):
        m = get_membership(request)
        qs = Membership.objects.filter(workspace=m.workspace).select_related("user")
        if request.query_params.get("active") == "1":
            qs = qs.filter(status=Membership.Status.ACTIVE)
        return Response(MemberSerializer(qs, many=True).data)


class MemberDetailView(APIView):
    def patch(self, request, pk):
        m = get_membership(request)
        require_role(m, *CONFIG)
        member = get_object_or_404(Membership, workspace=m.workspace, pk=pk)
        data = {}
        for field in ("title", "unavailable_until"):
            if field in request.data:
                value = request.data[field]
                if field == "unavailable_until":
                    from django.utils.dateparse import parse_date

                    value = parse_date(value) if value else None
                data[field] = value if value is not None else (None if field == "unavailable_until" else "")
        if "role" in request.data and request.data["role"] != member.role:
            role = request.data["role"]
            if role not in Role.values:
                raise BusinessRuleError("Unknown role.")
            if (role == Role.OWNER or member.role == Role.OWNER) and m.role != Role.OWNER:
                raise BusinessRuleError("Only an owner can change owner roles.")
            if member.pk == m.pk and role != m.role:
                raise BusinessRuleError("You cannot change your own role.")
            data["role"] = role
        for user_field in ("first_name", "last_name"):
            if user_field in request.data:
                setattr(member.user, user_field, request.data[user_field])
        member.user.save()
        changes = audit.diff(member, data.keys(), data)
        for k, v in data.items():
            setattr(member, k, v)
        member.save()
        audit.record(m.workspace, m, "member.updated", member, f"Updated {member.display_name}", changes)
        return Response(MemberSerializer(member).data)


class MemberActionView(APIView):
    def post(self, request, pk, action):
        m = get_membership(request)
        member = get_object_or_404(Membership, workspace=m.workspace, pk=pk)
        if action == "suspend":
            require_role(m, *CONFIG)
            services.suspend_member(m, member, request.data.get("reason") or "")
        elif action == "reactivate":
            require_role(m, *CONFIG)
            services.reactivate_member(m, member)
        elif action == "reassign":
            require_role(m, Role.OWNER, Role.ADMIN, Role.SALES_MANAGER, Role.DELIVERY_MANAGER)
            to = get_object_or_404(Membership, workspace=m.workspace, pk=request.data.get("to_member"))
            counts = services.reassign_work(m, member, to, request.data.get("reason") or "")
            return Response({"transferred": counts})
        elif action == "reset-mfa":
            require_role(m, Role.OWNER)
            member.mfa_enabled = False
            member.mfa_secret = ""
            member.save(update_fields=["mfa_enabled", "mfa_secret"])
            audit.record(m.workspace, m, "member.mfa_reset", member, f"Reset MFA for {member.display_name}")
        else:
            raise BusinessRuleError("Unknown action.")
        member.refresh_from_db()
        return Response(MemberSerializer(member).data)


class InvitationsView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        return Response(InvitationSerializer(Invitation.objects.filter(workspace=m.workspace), many=True).data)

    def post(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        inv = services.create_invitation(m, request.data.get("email") or "", request.data.get("role") or "", request.data.get("title") or "")
        return Response(InvitationSerializer(inv).data, status=201)


class InvitationRevokeView(APIView):
    def post(self, request, pk):
        from django.utils import timezone

        m = get_membership(request)
        require_role(m, *CONFIG)
        inv = get_object_or_404(Invitation, workspace=m.workspace, pk=pk)
        inv.revoked_at = timezone.now()
        inv.save(update_fields=["revoked_at"])
        audit.record(m.workspace, m, "invitation.revoked", inv, f"Revoked invitation for {inv.email}")
        return Response(InvitationSerializer(inv).data)


class WorkspaceSettingsView(APIView):
    def get(self, request):
        return Response(WorkspaceSerializer(get_membership(request).workspace).data)

    def patch(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        ser = WorkspaceSerializer(m.workspace, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        changes = audit.diff(m.workspace, ser.validated_data.keys(), ser.validated_data)
        ser.save()
        audit.record(m.workspace, m, "workspace.updated", ("workspace", m.workspace.pk), "Updated workspace settings", changes)
        return Response(ser.data)


class AuditLogView(APIView):
    def get(self, request):
        m = get_membership(request)
        require_role(m, *CONFIG)
        qs = AuditEvent.objects.filter(workspace=m.workspace).select_related("actor__user")
        for p in ("entity_type", "entity_id", "action"):
            if request.query_params.get(p):
                qs = qs.filter(**{p: request.query_params[p]})
        from modules.common.pagination import StandardPagination

        pager = StandardPagination()
        page = pager.paginate_queryset(qs, request, view=self)
        return pager.get_paginated_response(AuditEventSerializer(page, many=True).data)
