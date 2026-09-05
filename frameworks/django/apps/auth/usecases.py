"""DUMB Django shell: re-exports the USE CASES of the auth domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.auth_usecases` and the three frameworks share it;
here it is only re-exported so the endpoints can import from `apps.auth.usecases`.
"""

from __future__ import annotations

from shared.usecases.auth_usecases import active_tokens as active_tokens
from shared.usecases.auth_usecases import issue_token as issue_token
from shared.usecases.auth_usecases import revoke_token as revoke_token
from shared.usecases.auth_usecases import sessions_of_user as sessions_of_user
from shared.usecases.auth_usecases import tokens_of_user as tokens_of_user
from shared.usecases.result import Failure as Failure
