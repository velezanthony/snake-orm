"""Re-export of the shared auth view models, so the views import from their own layer.

The same seam every other domain makes: a view says `from apps.auth import viewmodels` and never
reaches across into `shared/` by hand. There is ONE shape here — the access ledger — because the
login and the registration answer with a redirect and a flash rather than with a page of rows.
"""

from __future__ import annotations

from shared.viewmodels.auth_viewmodels import access_ledger as access_ledger
