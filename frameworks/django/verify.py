#!/usr/bin/env python
"""One-command verification: runs the Django test-client suite and exits != 0 if anything fails.

    uv run python verify.py        # equivalent to `manage.py test apps`

It brings up no server: it uses `django.test.Client` (see `apps/blog/tests.py`).

The label is `apps` and not `apps.blog`, which it was until the inventory pages arrived. That single
word was a trap with a delay on it: the Makefile runs `manage.py test apps`, so a suite added to any
app OTHER than the blog ran there and did not run here, and the two commands that are supposed to
mean the same thing quietly stopped meaning it. `apps.inventory.tests` had been sitting there unrun
by this script the whole time. A verification that covers less than the gate it stands in for is
worse than none: it is a green that somebody trusts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The shared code lives in `frameworks/` (one folder above this app).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django
from django.conf import settings
from django.test.utils import get_runner


def main() -> int:
    """Boots Django and runs EVERY suite under `apps`; returns the number of failures as exit code."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
    runner = get_runner(settings)()
    failures = runner.run_tests(["apps"])
    return int(failures)


if __name__ == "__main__":
    sys.exit(main())
