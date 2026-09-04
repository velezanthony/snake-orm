"""Models of the logistics domain: re-exports the ones from the SHARED package (`shared.models`).

The framework declares NO models of its own; the metadata graph lives once in `shared` and here it
is only re-exposed (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import Delivery as Delivery
from shared.models import Depot as Depot
from shared.models import PackagingUnit as PackagingUnit
