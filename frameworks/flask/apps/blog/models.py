"""Models of the blog domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import Blog as Blog
from shared.models import BlogStats as BlogStats
from shared.models import Category as Category
from shared.models import Post as Post
