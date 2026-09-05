"""DUMB Django shell: re-exports the USE CASES of the content domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.content_usecases` and the three frameworks share it;
here it is only re-exported so the endpoints can import from `apps.content.usecases`.
"""

from __future__ import annotations

from shared.usecases.content_usecases import add_revision as add_revision
from shared.usecases.content_usecases import attach_file as attach_file
from shared.usecases.content_usecases import attachments_of_post as attachments_of_post
from shared.usecases.content_usecases import remove_attachment as remove_attachment
from shared.usecases.content_usecases import revisions_of_post as revisions_of_post
from shared.usecases.result import Failure as Failure
from shared.usecases.content_usecases import revision_timeline as revision_timeline
