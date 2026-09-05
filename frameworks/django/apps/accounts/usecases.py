"""DUMB Django shell: re-exports the USE CASES of the accounts domain, which live in `shared`.

Every use case takes a `SnakeSession` + FLAT parameters (no `request` at all), orchestrates services
and selectors, validates, commits and returns data or a framework-agnostic `Failure`. The
functionality is defined ONCE in `shared.usecases.accounts_usecases` and the three frameworks share
it; here it is only re-exported so the endpoints can import from `apps.accounts.usecases`.
"""

from __future__ import annotations

from shared.usecases.accounts_usecases import assign_role as assign_role
from shared.usecases.accounts_usecases import create_role as create_role
from shared.usecases.accounts_usecases import list_roles as list_roles
from shared.usecases.accounts_usecases import revoke_role as revoke_role
from shared.usecases.accounts_usecases import roles_of_user as roles_of_user
from shared.usecases.result import Failure as Failure
