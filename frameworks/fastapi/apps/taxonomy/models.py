"""Models of the taxonomy domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import TagGroup as TagGroup
from shared.models import Tag as Tag
from shared.models import PostTag as PostTag
