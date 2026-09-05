"""Framework-agnostic result shared by the use cases of the six API domains.

Same contract as the blog's `Failure`: a reason the web layer maps to its HTTP response. It lives
here once so the six domains (and their endpoints on the three frameworks) all translate alike.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    """A use case that did not complete, with a framework-AGNOSTIC reason.

    The web layer maps the `reason`: `missing_fields` → 400, `not_found` → 404, `conflict` → 409,
    `payment_declined` → 402.
    """

    reason: str


# Reason → HTTP status map, shared by the endpoints of the six domains (a single truth).
FAILURE_STATUS: dict[str, int] = {
    "missing_fields": 400,
    "not_found": 404,
    "conflict": 409,
    # A declined charge is not a conflict and not a bad request: the order was fine and the money did
    # not arrive. 402 is the only status that says that, and `settle` is the only operation that can
    # produce it — which is what a payment step being real rather than assumed looks like from here.
    "payment_declined": 402,
}
