"""Re-export of the shared accounts view models, so the views import from their own layer.

The same seam every other domain makes: a view says `from apps.accounts import viewmodels` and never
reaches across into `shared/` by hand. Moving the shape is then one line here instead of a grep.
"""

from __future__ import annotations

from shared.viewmodels.accounts_viewmodels import role_directory as role_directory
from shared.viewmodels.accounts_viewmodels import user_roles as user_roles
