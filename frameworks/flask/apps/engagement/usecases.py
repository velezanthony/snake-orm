"""Use cases of the engagement domain: it re-exports those of `shared.usecases` (they live only once)."""

from shared.usecases.engagement_usecases import add_comment as add_comment
from shared.usecases.engagement_usecases import add_reaction as add_reaction
from shared.usecases.engagement_usecases import comments_of_post as comments_of_post
from shared.usecases.engagement_usecases import reactions_of_post as reactions_of_post
from shared.usecases.engagement_usecases import record_visit as record_visit
from shared.usecases.engagement_usecases import visits_of_post as visits_of_post
from shared.usecases.result import Failure as Failure
from shared.usecases.engagement_usecases import stream_visits as stream_visits
