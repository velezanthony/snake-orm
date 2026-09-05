"""Models of the inventory domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import MovementReason as MovementReason
from shared.models import Sku as Sku
from shared.models import SkuKind as SkuKind
from shared.models import Stock as Stock
from shared.models import StockMovement as StockMovement
from shared.models import Warehouse as Warehouse
from shared.models import WarehouseStats as WarehouseStats
