"""The sidecar buffer: recent reports by token, served at `/__snake__/{token}`.

A bounded ring buffer over `OrderedDict`: in a long-lived process it does not grow without limit (the footgun of Django's global `connection.queries`).
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict

from snakeorm.debug import DebugReport


def new_token() -> str:
    """A short, unguessable token to reference a report from the response."""
    return secrets.token_urlsafe(9)


class SidecarBuffer:
    """Keep the last N reports by token, evicting the oldest one when it fills up.

    With a lock: a WSGI server is multithreaded and `store()` does three non-atomic operations together on the `OrderedDict`.
    """

    __slots__ = ("_store", "_capacity", "_lock")

    def __init__(self, capacity: int = 50) -> None:
        self._store: OrderedDict[str, DebugReport] = OrderedDict()
        self._capacity = capacity
        self._lock = threading.Lock()

    def store(self, token: str, report: DebugReport) -> None:
        """Store a report under its token, evicting the oldest one if the capacity is exceeded."""
        with self._lock:
            self._store[token] = report
            self._store.move_to_end(token)
            while len(self._store) > self._capacity:
                self._store.popitem(last=False)

    def get(self, token: str) -> DebugReport | None:
        """The report of that token, or `None` if it is gone (expired) or never existed."""
        with self._lock:
            return self._store.get(token)
