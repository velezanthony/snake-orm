"""Services of the taxonomy domain: it re-exports those of the SHARED package (`shared.services`)."""

from __future__ import annotations

from shared.services.taxonomy_services import create_tag as create_tag
from shared.services.taxonomy_services import tag_post as tag_post
from shared.services.taxonomy_services import untag_post as untag_post
