"""Vercel serverless entry point: serves the Django API (apps/api) for every /api/* request.

vercel.json rewrites /api/* here; Django sees the original path and routes it as usual.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps" / "api"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
