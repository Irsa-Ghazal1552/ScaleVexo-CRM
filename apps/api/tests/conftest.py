import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from modules.identity.models import Membership, Role
from modules.identity.services import create_workspace

User = get_user_model()
PASSWORD = "Test-Password-2026"


@pytest.fixture
def workspace(db, settings):
    settings.REQUIRE_MFA_FOR_PRIVILEGED = False
    ws, owner = create_workspace("Test Co", "ceo@test.local", PASSWORD, "Chief", "Exec")
    return ws


@pytest.fixture
def make_member(workspace):
    def _make(key, role):
        user = User.objects.create_user(username=f"{key}@test.local", email=f"{key}@test.local", password=PASSWORD, first_name=key.title())
        return Membership.objects.create(workspace=workspace, user=user, role=role)

    return _make


@pytest.fixture
def team(workspace, make_member):
    return {
        "owner": Membership.objects.get(workspace=workspace, role=Role.OWNER),
        "manager": make_member("manager", Role.SALES_MANAGER),
        "rep1": make_member("rep1", Role.SALES_REP),
        "rep2": make_member("rep2", Role.SALES_REP),
        "dm": make_member("dm", Role.DELIVERY_MANAGER),
        "dev": make_member("dev", Role.DELIVERY_EMPLOYEE),
        "admin": make_member("admin", Role.ADMIN),
    }


@pytest.fixture
def client_for():
    def _client(member):
        c = APIClient()
        c.force_authenticate(user=None)
        c.login(username=member.user.username, password=PASSWORD)
        return c

    return _client
