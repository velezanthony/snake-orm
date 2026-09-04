"""Selectors of the inventory domain: it re-exports those of `shared.selectors` (they live only once)."""

from shared.selectors.inventory_selectors import get_sku as get_sku
from shared.selectors.inventory_selectors import get_stock as get_stock
from shared.selectors.inventory_selectors import get_warehouse as get_warehouse
from shared.selectors.inventory_selectors import list_skus as list_skus
from shared.selectors.inventory_selectors import list_warehouses as list_warehouses
from shared.selectors.inventory_selectors import movements_of as movements_of
from shared.selectors.inventory_selectors import skus_in_warehouse as skus_in_warehouse
from shared.selectors.inventory_selectors import (
    stock_of_warehouse as stock_of_warehouse,
)
from shared.selectors.inventory_selectors import (
    stock_with_movements as stock_with_movements,
)
from shared.selectors.inventory_selectors import warehouse_stats as warehouse_stats
from shared.selectors.inventory_selectors import (
    warehouses_holding_anything as warehouses_holding_anything,
)
from shared.selectors.inventory_selectors import with_at_least as with_at_least
