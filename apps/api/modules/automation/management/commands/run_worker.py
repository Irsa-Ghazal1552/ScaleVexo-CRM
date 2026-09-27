import os
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from modules.automation.engine import run_all


class Command(BaseCommand):
    help = "Background worker: evaluates rules A01-A08 on a fixed interval."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
        parser.add_argument("--interval", type=int, default=int(os.environ.get("WORKER_INTERVAL_SECONDS", "60")))

    def handle(self, *args, **options):
        stop = {"flag": False}

        def _stop(*_):
            stop["flag"] = True

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        self.stdout.write(f"Rule worker started (interval {options['interval']}s)")
        while not stop["flag"]:
            close_old_connections()
            try:
                summary = run_all()
                self.stdout.write(f"Rules evaluated for {len(summary)} workspace(s)")
            except Exception as exc:  # keep the worker alive; errors are logged
                self.stderr.write(f"Worker cycle failed: {exc}")
            if options["once"]:
                break
            for _ in range(options["interval"]):
                if stop["flag"]:
                    break
                time.sleep(1)
        self.stdout.write("Rule worker stopped")
