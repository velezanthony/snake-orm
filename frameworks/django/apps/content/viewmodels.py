"""Re-export of the shared content view models, so the views import from their own layer.

The same seam every other domain makes: a view says `from apps.content import viewmodels` and never
reaches across into `shared/` by hand. Moving the shape is then one line here instead of a grep.
"""

from __future__ import annotations

from shared.viewmodels.content_viewmodels import post_content as post_content
from shared.viewmodels.content_viewmodels import post_index as post_index
