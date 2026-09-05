"""Use cases of the orders domain: it re-exports those of `shared.usecases` (they live only once).

`PaymentDeclined` and `accept_every_charge` travel with the rest even though no view of this demo
raises one. They are the seam `settle` takes its money through, and a demo that hid them would be
hiding the only step of the flow that is not a database write — which is precisely the step the
savepoint exists for.
"""

from shared.usecases.orders_usecases import PaymentDeclined as PaymentDeclined
from shared.usecases.orders_usecases import accept_every_charge as accept_every_charge
from shared.usecases.orders_usecases import attach_invoice as attach_invoice
from shared.usecases.orders_usecases import cancel_order as cancel_order
from shared.usecases.orders_usecases import customer_orders as customer_orders
from shared.usecases.orders_usecases import get_order as get_order
from shared.usecases.orders_usecases import list_orders as list_orders
from shared.usecases.orders_usecases import order_lines as order_lines
from shared.usecases.orders_usecases import orders_of_customer as orders_of_customer
from shared.usecases.orders_usecases import orders_per_state as orders_per_state
from shared.usecases.orders_usecases import paginate_orders as paginate_orders
from shared.usecases.orders_usecases import place_order as place_order
from shared.usecases.orders_usecases import remove_line as remove_line
from shared.usecases.orders_usecases import remove_order as remove_order
from shared.usecases.orders_usecases import reserve as reserve
from shared.usecases.orders_usecases import set_line as set_line
from shared.usecases.orders_usecases import settle as settle
from shared.usecases.orders_usecases import order_report as order_report
from shared.usecases.orders_usecases import stream_order_lines as stream_order_lines
from shared.usecases.result import Failure as Failure
