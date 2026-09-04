"""DUMB Django shell: re-exports the USE CASES of the engagement domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.engagement_usecases` and the three frameworks share it;
here it is only re-exported so the endpoints can import from `apps.engagement.usecases`.
"""

from __future__ import annotations

from shared.usecases.engagement_usecases import add_comment as add_comment
from shared.usecases.engagement_usecases import add_reaction as add_reaction
from shared.usecases.engagement_usecases import comments_of_post as comments_of_post
from shared.usecases.engagement_usecases import reactions_of_post as reactions_of_post
from shared.usecases.engagement_usecases import record_visit as record_visit
from shared.usecases.engagement_usecases import visits_of_post as visits_of_post
from shared.usecases.result import Failure as Failure
from shared.usecases.engagement_usecases import stream_visits as stream_visits
