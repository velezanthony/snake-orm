"""Use cases of the accounts domain: it re-exports those of `shared.usecases` (they live only once)."""

from shared.usecases.accounts_usecases import assign_role as assign_role
from shared.usecases.accounts_usecases import create_role as create_role
from shared.usecases.accounts_usecases import list_roles as list_roles
from shared.usecases.accounts_usecases import revoke_role as revoke_role
from shared.usecases.accounts_usecases import roles_of_user as roles_of_user
from shared.usecases.result import Failure as Failure
