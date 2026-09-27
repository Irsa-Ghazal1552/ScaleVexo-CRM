import os

from django.core.management.base import BaseCommand, CommandError

from modules.identity.models import Workspace
from modules.identity.services import create_workspace, ensure_workspace_defaults


class Command(BaseCommand):
    help = "Create the first workspace and its owner (CEO) account. Safe to run repeatedly."

    def add_arguments(self, parser):
        parser.add_argument("--name", default=os.environ.get("WORKSPACE_NAME", "ScaleVexo"))
        parser.add_argument("--owner-email", default=os.environ.get("OWNER_EMAIL"))
        parser.add_argument("--owner-password", default=os.environ.get("OWNER_PASSWORD"))
        parser.add_argument("--owner-first-name", default=os.environ.get("OWNER_FIRST_NAME", ""))
        parser.add_argument("--owner-last-name", default=os.environ.get("OWNER_LAST_NAME", ""))
        parser.add_argument("--timezone", default=os.environ.get("WORKSPACE_TIMEZONE", "Asia/Karachi"))

    def handle(self, *args, **o):
        existing = Workspace.objects.first()
        if existing:
            ensure_workspace_defaults(existing)
            self.stdout.write(f"Workspace already exists: {existing.name}")
            return
        if not o["owner_email"] or not o["owner_password"]:
            raise CommandError("Set OWNER_EMAIL and OWNER_PASSWORD (or pass --owner-email / --owner-password).")
        if len(o["owner_password"]) < 10:
            raise CommandError("OWNER_PASSWORD must be at least 10 characters.")
        ws, owner = create_workspace(o["name"], o["owner_email"], o["owner_password"], o["owner_first_name"], o["owner_last_name"], o["timezone"])
        self.stdout.write(self.style.SUCCESS(f"Created workspace '{ws.name}' with owner {owner.user.email}"))
