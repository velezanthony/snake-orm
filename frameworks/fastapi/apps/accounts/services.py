"""Services of the accounts domain: it re-exports those of the SHARED package (`shared.services`)."""

from __future__ import annotations

from shared.services.accounts_services import create_role as create_role
from shared.services.accounts_services import assign_role as assign_role
from shared.services.accounts_services import revoke_role as revoke_role
