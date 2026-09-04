"""The sidecar buffer: it keeps reports by token so `/__snake__/{token}` can serve them.

Bounded on purpose (ring buffer): inside a live process it cannot grow without a limit —the memory
footgun of Django's global `connection.queries`—. Once it is full, the oldest one drops.
"""

from __future__ import annotations

from snakeorm.contrib.sidecar import SidecarBuffer, new_token
from snakeorm.debug import DebugReport


def _report() -> DebugReport:
    return DebugReport.from_records([])


def test_store_and_get_roundtrip() -> None:
    """A report stored under a token is retrieved by that token."""
    buffer = SidecarBuffer(capacity=4)
    report = _report()
    buffer.store("abc", report)
    assert buffer.get("abc") is report


def test_missing_token_returns_none() -> None:
    """A token that does not exist returns None, it does not blow up."""
    assert SidecarBuffer().get("nope") is None


def test_oldest_is_evicted_when_full() -> None:
    """Once capacity is exceeded, the oldest report drops: memory stays bounded."""
    buffer = SidecarBuffer(capacity=2)
    buffer.store("a", _report())
    buffer.store("b", _report())
    buffer.store("c", _report())  # evicts "a"
    assert buffer.get("a") is None
    assert buffer.get("b") is not None
    assert buffer.get("c") is not None


def test_new_token_is_unique_enough() -> None:
    """`new_token` yields different tokens on successive calls (no collision by eye)."""
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
