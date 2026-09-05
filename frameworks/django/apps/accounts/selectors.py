"""Selectors of the accounts domain: re-exports the ones from the SHARED package (`shared.selectors`)."""

from __future__ import annotations

from shared.selectors.accounts_selectors import list_roles as list_roles
from shared.selectors.accounts_selectors import get_role as get_role
from shared.selectors.accounts_selectors import roles_of_user as roles_of_user
