"""DUMB shell: re-exports the USE CASES of the logistics domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.logistics_usecases` and the three frameworks share
it; here it is only re-exported so the views and the endpoints can import from `apps.logistics.usecases`.
"""

from __future__ import annotations

from shared.usecases.logistics_usecases import DeliverySheet as DeliverySheet
from shared.usecases.logistics_usecases import DepotSummary as DepotSummary
from shared.usecases.logistics_usecases import DispatchEntry as DispatchEntry
from shared.usecases.logistics_usecases import SlotBand as SlotBand
from shared.usecases.logistics_usecases import delivery_sheet as delivery_sheet
from shared.usecases.logistics_usecases import dispatch_board as dispatch_board
from shared.usecases.logistics_usecases import list_depots as list_depots
from shared.usecases.logistics_usecases import reroute_delivery as reroute_delivery
from shared.usecases.logistics_usecases import slot_load as slot_load
from shared.usecases.result import Failure as Failure
