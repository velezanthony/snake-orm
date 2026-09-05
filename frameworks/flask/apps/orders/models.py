"""Models of the orders domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import CustomerOrders as CustomerOrders
from shared.models import Order as Order
from shared.models import OrderLine as OrderLine
from shared.models import OrderState as OrderState
