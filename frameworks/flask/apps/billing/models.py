"""Models of the billing domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import Plan as Plan
from shared.models import Subscription as Subscription
from shared.models import Invoice as Invoice
from shared.models import Payment as Payment
from shared.models import PlanStats as PlanStats
