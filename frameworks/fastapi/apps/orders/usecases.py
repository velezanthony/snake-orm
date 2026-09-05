"""Use cases of the orders domain: it re-exports the ASYNCHRONOUS ones from `shared.aio`.

The demo is ASGI, so this router awaits an `AsyncSession`. The synchronous twin of every function
here lives in `shared.usecases.orders_usecases` and serves the Django and Flask demos; the two are
held together by `shared/tests/test_async_mirror.py` (same names, same parameters) and
`shared/tests/test_sync_async_parity.py` (same answer, same SQL, same message).

This is the domain where that pair of nets earns its keep. `reserve` declares an isolation level and
locks rows; `settle` opens a savepoint, lets it rewind and keeps writing afterwards — three things
that are easy to write twice and easy to write differently the second time.
"""

from shared.aio.orders_usecases import accept_every_charge as accept_every_charge
from shared.aio.orders_usecases import attach_invoice as attach_invoice
from shared.aio.orders_usecases import cancel_order as cancel_order
from shared.aio.orders_usecases import customer_orders as customer_orders
from shared.aio.orders_usecases import get_order as get_order
from shared.aio.orders_usecases import list_orders as list_orders
from shared.aio.orders_usecases import order_lines as order_lines
from shared.aio.orders_usecases import order_report as order_report
from shared.aio.orders_usecases import orders_of_customer as orders_of_customer
from shared.aio.orders_usecases import orders_per_state as orders_per_state
from shared.aio.orders_usecases import paginate_orders as paginate_orders
from shared.aio.orders_usecases import place_order as place_order
from shared.aio.orders_usecases import remove_line as remove_line
from shared.aio.orders_usecases import remove_order as remove_order
from shared.aio.orders_usecases import reserve as reserve
from shared.aio.orders_usecases import set_line as set_line
from shared.aio.orders_usecases import settle as settle
from shared.aio.orders_usecases import stream_order_lines as stream_order_lines
from shared.usecases.result import Failure as Failure
