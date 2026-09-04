"""DUMB Django shell: re-exports the USE CASES of the taxonomy domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.taxonomy_usecases` and the three frameworks share it;
here it is only re-exported so the endpoints can import from `apps.taxonomy.usecases`.
"""

from __future__ import annotations

from shared.usecases.result import Failure as Failure
from shared.usecases.taxonomy_usecases import create_tag as create_tag
from shared.usecases.taxonomy_usecases import list_groups as list_groups
from shared.usecases.taxonomy_usecases import list_tags as list_tags
from shared.usecases.taxonomy_usecases import (
    posts_with_every_tag as posts_with_every_tag,
)
from shared.usecases.taxonomy_usecases import (
    posts_with_tag_but_not as posts_with_tag_but_not,
)
from shared.usecases.taxonomy_usecases import tag_post as tag_post
from shared.usecases.taxonomy_usecases import tags_of_post as tags_of_post
from shared.usecases.taxonomy_usecases import untag_post as untag_post
from shared.usecases.taxonomy_usecases import tag_breadcrumb as tag_breadcrumb
from shared.usecases.taxonomy_usecases import tag_descendants as tag_descendants
