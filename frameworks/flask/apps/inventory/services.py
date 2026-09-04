"""Services of the inventory domain: it re-exports those of `shared.services` (they live only once)."""

from shared.services.inventory_services import close_warehouse as close_warehouse
from shared.services.inventory_services import create_sku as create_sku
from shared.services.inventory_services import create_skus as create_skus
from shared.services.inventory_services import create_warehouse as create_warehouse
from shared.services.inventory_services import delete_stock as delete_stock
from shared.services.inventory_services import move_stock as move_stock
from shared.services.inventory_services import reserve_units as reserve_units
from shared.services.inventory_services import set_stock as set_stock
from shared.services.inventory_services import sku_by_public_id as sku_by_public_id
