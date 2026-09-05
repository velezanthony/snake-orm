"""The port the Makefile STARTS a demo on, and the one the React client PROXIES to.

Two files hold this, and they have to agree or the fourth demo talks to nothing. They had already
drifted: `make fastapi-dev` ran uvicorn on its default 8000 while `backends.ts` proxied to 8001, so
`make fastapi-dev` together with `make react-dev` could not reach each other. Nothing was wrong in
either file on its own, which is why it survived — the mistake only exists BETWEEN them.

Parsed rather than imported, and that is not laziness: one side is a Makefile and the other is
TypeScript, so there is no runtime where both are values. What can be shared is the assertion.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_MAKEFILE = _ROOT / "Makefile"
_BACKENDS = _ROOT / "frameworks/react_front/src/config/backends.ts"

# `make flask-dev` takes the port from Flask's own default rather than a variable, so the Makefile
# names it only in the help line. It is read from there, which is the string a person actually
# follows.
_MAKEFILE_PORTS = {
    "django": re.compile(r"^DJANGO_PORT \?= (\d+)$", re.MULTILINE),
    "fastapi": re.compile(r"^FASTAPI_PORT \?= (\d+)$", re.MULTILINE),
    "flask": re.compile(r"^flask-dev:.*?127\.0\.0\.1:(\d+)", re.MULTILINE),
}


def _makefile_port(demo: str) -> str:
    """What `make <demo>-dev` brings the app up on."""
    found = _MAKEFILE_PORTS[demo].search(_MAKEFILE.read_text(encoding="utf-8"))
    assert found is not None, f"the Makefile no longer states a port for {demo}"
    return found.group(1)


def _client_port(demo: str) -> str:
    """What the React client's proxy sends that backend's traffic to."""
    block = re.search(
        rf'{demo}: \{{.*?origin: "http://127\.0\.0\.1:(\d+)"',
        _BACKENDS.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert block is not None, f"`backends.ts` no longer states an origin for {demo}"
    return block.group(1)


@pytest.mark.parametrize("demo", ["django", "flask", "fastapi"])
def test_the_makefile_and_the_client_name_the_same_port(demo: str) -> None:
    """One case per demo, so the failure names the one that moved."""
    started, proxied = _makefile_port(demo), _client_port(demo)

    assert started == proxied, (
        f"`make {demo}-dev` serves on {started} and the React client proxies to {proxied}. "
        "Move whichever is wrong — they are the same fact written twice."
    )


def test_the_three_demos_hold_different_ports() -> None:
    """All three up AT ONCE, which is what makes the client's backend switcher worth having.

    It changes backend without restarting anything, so a shared port turns the switch into "stop
    that one, start this one" — and the feature is then a lie told by a dropdown. Django and FastAPI
    both defaulted to 8000 until this was written.
    """
    ports = {demo: _makefile_port(demo) for demo in ("django", "flask", "fastapi")}

    assert len(set(ports.values())) == 3, f"two demos share a port: {ports}"
