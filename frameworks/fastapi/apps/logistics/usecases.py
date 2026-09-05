"""DUMB ASGI shell: re-exports the ASYNCHRONOUS use cases of the logistics domain.

This demo is the asynchronous one, so what it re-exports is `shared.aio.logistics_usecases` — the
twin of the synchronous module the other two frameworks take. `test_async_mirror.py` holds the two to
the same names and the same parameters, so this file being a mirror of Django's and Flask's is a fact
rather than a convention.
"""

from __future__ import annotations

from shared.aio.logistics_usecases import delivery_sheet as delivery_sheet
from shared.aio.logistics_usecases import dispatch_board as dispatch_board
from shared.aio.logistics_usecases import list_depots as list_depots
from shared.aio.logistics_usecases import reroute_delivery as reroute_delivery
from shared.aio.logistics_usecases import slot_load as slot_load
from shared.usecases.logistics_usecases import DeliverySheet as DeliverySheet
from shared.usecases.logistics_usecases import DepotSummary as DepotSummary
from shared.usecases.logistics_usecases import DispatchEntry as DispatchEntry
from shared.usecases.logistics_usecases import SlotBand as SlotBand
from shared.usecases.result import Failure as Failure
