"""Use cases of the content domain: it re-exports those of `shared.usecases` (they live only once)."""

from shared.usecases.content_usecases import add_revision as add_revision
from shared.usecases.content_usecases import attach_file as attach_file
from shared.usecases.content_usecases import attachments_of_post as attachments_of_post
from shared.usecases.content_usecases import remove_attachment as remove_attachment
from shared.usecases.content_usecases import revisions_of_post as revisions_of_post
from shared.usecases.result import Failure as Failure
from shared.usecases.content_usecases import revision_timeline as revision_timeline
