"""Re-export of the shared taxonomy view models, so the views import from their own layer.

The same seam every other domain makes: a view says `from apps.taxonomy import viewmodels` and never
reaches across into `shared/` by hand. Moving the shape is then one line here instead of a grep.
"""

from __future__ import annotations

from shared.viewmodels.taxonomy_viewmodels import NOTHING_ASKED as NOTHING_ASKED
from shared.viewmodels.taxonomy_viewmodels import filtered_posts as filtered_posts
from shared.viewmodels.taxonomy_viewmodels import post_tags as post_tags
from shared.viewmodels.taxonomy_viewmodels import tag_form as tag_form
from shared.viewmodels.taxonomy_viewmodels import tag_list as tag_list
from shared.viewmodels.taxonomy_viewmodels import tag_tree as tag_tree
