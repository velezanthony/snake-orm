"""Services of the content domain: it re-exports those of the SHARED package (`shared.services`)."""

from __future__ import annotations

from shared.services.content_services import add_revision as add_revision
from shared.services.content_services import attach_file as attach_file
from shared.services.content_services import remove_attachment as remove_attachment
