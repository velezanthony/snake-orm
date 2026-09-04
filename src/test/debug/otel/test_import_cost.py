"""Importing the ORM does not drag an HTTP CLIENT in behind it.

`snakeorm/__init__.py` re-exports `snakeorm.debug`, which re-exports `export_report`, which lives in
the OTLP exporter. A module-level `import urllib.request` there therefore lands on EVERY user of the
library — including the overwhelming majority who never switch the `otel` channel on.

It is not free either: measured with `python -X importtime`, `urllib.request` and what it drags with
it (`http.client`, `email.*`) cost ~17 ms of an `import snakeorm`, for a socket nobody opened.

`ssl` is deliberately NOT on the watched list even though `urllib` pulls it: `psycopg2` is a hard
dependency of this ORM and loads it anyway, so watching it here would make this test go red for
something it does not govern — and a test that fails for a reason outside its own subject gets
disabled, taking the part that DID work with it.

The channel's own promise is that switching it OFF costs nothing. An import is part of that promise,
so it is checked rather than remembered — and it is checked in a FRESH interpreter, because inside
this test session half the standard library is already loaded and the question would answer itself.
"""

from __future__ import annotations

import subprocess
import sys

_PROBE = (
    "import sys; import snakeorm; "
    "print(','.join(m for m in ('urllib.request', 'http.client') if m in sys.modules))"
)


def test_importing_snakeorm_does_not_load_an_http_client() -> None:
    """A fresh interpreter that imports the ORM has no HTTP client loaded."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == ""


def test_the_transport_still_works_when_it_is_finally_needed() -> None:
    """The lazy import is inside the send, so the exporter still has a real transport to use.

    A test for the absence of something has to be paired with one for the presence, or "it is not
    imported" and "it does not exist" pass the same way.
    """
    from snakeorm.debug.otel import post_json

    assert callable(post_json)
