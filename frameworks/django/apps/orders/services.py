"""Services of the orders domain: it re-exports those of `shared.services` (they live only once)."""

from shared.services.orders_services import add_lines as add_lines
from shared.services.orders_services import attach_invoice as attach_invoice
from shared.services.orders_services import create_order as create_order
from shared.services.orders_services import delete_line as delete_line
from shared.services.orders_services import delete_order as delete_order
from shared.services.orders_services import retotal as retotal
from shared.services.orders_services import set_line as set_line
from shared.services.orders_services import set_state as set_state
