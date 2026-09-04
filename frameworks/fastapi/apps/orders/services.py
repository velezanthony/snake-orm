"""Services of the orders domain: it re-exports those of the SHARED package (`shared.services`).

They are the SYNCHRONOUS writes, and this router does not call them: an `AsyncSession` cannot, since
a statement has a colour. They are re-exported anyway so the ten domains read alike from the outside
and so `shared/tests/test_selectors_and_services.py` finds this demo's copy where it finds the other
two — the asynchronous half of each of these lives inlined in `shared/aio/orders_usecases.py`, which
is where `await` forced it to go.
"""

from __future__ import annotations

from shared.services.orders_services import create_order as create_order
from shared.services.orders_services import set_line as set_line
from shared.services.orders_services import set_state as set_state
from shared.services.orders_services import attach_invoice as attach_invoice
