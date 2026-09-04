"""Opens a working session before the app is imported, so this run gets a database of its own.

The demo builds its schema at import time — `drop_all` and the migrations, or `init_schema` — so by
the time the first test runs the database has already been chosen and rebuilt. `conftest.py` is
loaded before any test module, which makes it the last place where the choice can still be made.

WHY IT IS A FILE AND NOT A LINE IN THE MAKEFILE. `make frameworks-test-flask` is one way in and
`cd frameworks/flask && uv run pytest` is the other, and the second is the one people actually type
while working on the demo. A mitigation that only holds through the Makefile is a mitigation that
depends on somebody remembering which command to use — which is the shape of the thing this exists
to replace.

Nothing here is claimed twice: `claim()` is `setdefault`, so a run started from another run inherits
its parent's session instead of pointing somewhere else.
"""

from __future__ import annotations

import pytest

from shared.session import claim

claim()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Removes the database this run created. The ORM suite's sweep is for the runs that crash.

    A run that ends normally cleans up after itself, because relying only on the sweep means
    anybody who works exclusively on the demos accumulates one database per run until they happen to
    run `uv run pytest`. `close_session` does nothing when there is no session id, so the demo's real
    database — the one `make flask-dev` serves — is never what gets dropped here.

    `shared.config` is imported inside the hook and not at the top of the file: this module is loaded
    before the app, and the whole point of being loaded that early is not to drag the domain graph in
    with it.
    """
    from shared.config import close_session

    close_session("flask")
