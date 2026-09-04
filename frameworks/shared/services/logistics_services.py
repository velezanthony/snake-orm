"""logistics domain — SERVICES: the one thing this domain WRITES, and why it is the only one.

Every framework re-exports them from `apps/logistics/services.py`.

THE DOMAIN READS AND WRITES EXACTLY ONE FIELD, and the asymmetry is the design rather than an
unfinished section. Deliveries are booked by whatever system takes the customer's order; a depot's
position is surveyed once; a box size is a fact about cardboard. None of the three is something a
dispatcher edits from a screen, and a form that let one be typed would be a demo of a thing no
logistics application offers.

What a dispatcher DOES do is move a delivery to the right depot, and that is the write here — the
one the domain's own reading makes obvious the moment it is drawn: the sheet ranks the depots by
distance, the assigned one is somewhere in that ranking, and when it is not the first the page is
looking at a van driving further than it has to.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Delivery


def route_to(session: SnakeSession, delivery: Delivery, depot_id: int) -> None:
    """Points a delivery at a depot. The caller has already decided WHICH; this only writes it.

    The decision is in the use case and not in here on purpose. Picking a depot is a question about
    the whole table — the nearest one — and this layer's job is the change, so a service that ran the
    ranking itself would make "reroute" and "reroute to the depot I chose" the same function with two
    meanings.
    """
    delivery.depot_id = depot_id
    session.update(delivery)
