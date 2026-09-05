"""Use cases of the inventory domain: it re-exports those of `shared.usecases` (they live only once)."""

from shared.usecases.inventory_usecases import count_stock as count_stock
from shared.usecases.inventory_usecases import create_sku as create_sku
from shared.usecases.inventory_usecases import create_warehouse as create_warehouse
from shared.usecases.inventory_usecases import get_stock as get_stock
from shared.usecases.inventory_usecases import get_warehouse as get_warehouse
from shared.usecases.inventory_usecases import list_skus as list_skus
from shared.usecases.inventory_usecases import low_stock as low_stock
from shared.usecases.inventory_usecases import movement_book as movement_book
from shared.usecases.inventory_usecases import list_warehouses as list_warehouses
from shared.usecases.inventory_usecases import movements_of as movements_of
from shared.usecases.inventory_usecases import paginate_stock as paginate_stock
from shared.usecases.inventory_usecases import receive as receive
from shared.usecases.inventory_usecases import remove_stock as remove_stock
from shared.usecases.inventory_usecases import reserve as reserve
from shared.usecases.inventory_usecases import ship as ship
from shared.usecases.inventory_usecases import stock_of_warehouse as stock_of_warehouse
from shared.usecases.inventory_usecases import stock_report as stock_report
from shared.usecases.inventory_usecases import (
    stock_with_movements as stock_with_movements,
)
from shared.usecases.inventory_usecases import stream_movements as stream_movements
from shared.usecases.inventory_usecases import update_stock as update_stock
from shared.usecases.inventory_usecases import warehouse_stats as warehouse_stats
from shared.usecases.result import Failure as Failure
