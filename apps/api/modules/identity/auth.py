from django.conf import settings
from django.contrib.auth import logout
from rest_framework import exceptions, permissions
from rest_framework.authentication import SessionAuthentication

from .models import PRIVILEGED_ROLES, Membership, Role


def membership_for(user):
    if not user or not user.is_authenticated:
        return None
    return Membership.objects.select_related("workspace", "user").filter(user=user).order_by("created_at").first()


class MembershipSessionAuthentication(SessionAuthentication):
    """Session auth (with CSRF) that also rejects suspended members on every request (CRM01)."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, auth = result
        membership = membership_for(user)
        if membership is None or not membership.is_active:
            logout(request._request)
            raise exceptions.AuthenticationFailed("Your access to this workspace has been suspended.")
        request._request.membership = membership
        return user, auth

    def authenticate_header(self, request):
        return "Session"


def get_membership(request):
    membership = getattr(request, "membership", None) or getattr(request._request, "membership", None)
    if membership is None:
        raise exceptions.NotAuthenticated()
    return membership


def mfa_setup_pending(membership):
    return (
        settings.REQUIRE_MFA_FOR_PRIVILEGED
        and membership.role in PRIVILEGED_ROLES
        and not membership.mfa_enabled
    )


class IsActiveMember(permissions.BasePermission):
    message = "Sign in to continue."

    def has_permission(self, request, view):
        membership = getattr(request._request, "membership", None)
        if membership is None or not membership.is_active:
            return False
        if mfa_setup_pending(membership) and not getattr(view, "allow_without_mfa", False):
            raise exceptions.PermissionDenied(detail="Multi-factor authentication must be set up first.", code="mfa_setup_required")
        return True


def has_role(membership, *roles):
    return membership is not None and membership.role in roles


def require_role(membership, *roles, message="You do not have permission to do this."):
    if not has_role(membership, *roles):
        raise exceptions.PermissionDenied(message)


# Named capability groups used across modules
SALES_ALL = (Role.OWNER, Role.SALES_MANAGER)
SALES_ANY = (Role.OWNER, Role.SALES_MANAGER, Role.SALES_REP)
DELIVERY_ALL = (Role.OWNER, Role.DELIVERY_MANAGER)
MANAGERS = (Role.OWNER, Role.SALES_MANAGER, Role.DELIVERY_MANAGER)
CONFIG = (Role.OWNER, Role.ADMIN)
