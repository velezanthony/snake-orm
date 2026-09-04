"""Models of the blog domain: re-exports the ones from the SHARED package (`shared.models`).

The framework declares NO models of its own; the metadata graph lives once in `shared` and here it
is only re-exposed (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import Blog as Blog
from shared.models import BlogStats as BlogStats
from shared.models import Category as Category
from shared.models import Post as Post
