#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys
from pathlib import Path

# The shared code lives in `frameworks/` (one folder above this app).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    """Run administrative tasks.

    `test` opens a working session before Django reads its settings, so this run gets a database of
    its own and cannot rebuild the schema another run is halfway through reading. Only `test`: a
    `runserver` that claimed a session would come up on an empty database every time it restarted,
    and the demo you seeded would look broken.

    Here and not in a `conftest.py` because Django's suite is run by `manage.py test`, which never
    loads one. The claim has to happen before `config.settings` is imported — settings is where the
    database name is decided — and that is the line below.

    AND THE DATABASE IS REMOVED AT THE END, in a `finally`, which is the only reason the command is
    wrapped at all: `manage.py test` ends by calling `sys.exit()` when something fails, so anything
    written after it would run on a green suite and never on a red one — cleaning up exactly when
    there is nothing to clean up. This is the sibling of the `pytest_sessionfinish` the other three
    suites have; without it, Django would be the one suite that left a database per run behind and
    the sweep would be carrying it alone.
    """
    testing = len(sys.argv) > 1 and sys.argv[1] == "test"
    if testing:
        from shared.session import claim

        claim()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    try:
        execute_from_command_line(sys.argv)
    finally:
        if testing:
            from shared.config import close_session

            close_session("django")


if __name__ == "__main__":
    main()
