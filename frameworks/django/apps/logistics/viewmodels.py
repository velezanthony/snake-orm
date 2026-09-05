"""Re-export of the shared logistics view models, so the views import from their own layer.

The same seam every other domain makes: a view says `from apps.logistics import viewmodels` and never
reaches across into `shared/` by hand. Moving the shape is then one line here instead of a grep.
"""

from __future__ import annotations

from shared.viewmodels.logistics_viewmodels import delivery_sheet as delivery_sheet
from shared.viewmodels.logistics_viewmodels import depot_list as depot_list
from shared.viewmodels.logistics_viewmodels import dispatch_board as dispatch_board
from shared.viewmodels.logistics_viewmodels import reroute as reroute
from shared.viewmodels.logistics_viewmodels import slot_load as slot_load
