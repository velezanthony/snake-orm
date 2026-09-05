"""accounts domain (roles) use cases: the complete operation of each action, written once.

They orchestrate selectors (reads) and services (writes), validate and commit, and take only flat
parameters, returning data or a `Failure`. The endpoints of the three frameworks are just the skin.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Role, UserRole
from shared.selectors import accounts_selectors as selectors
from shared.services import accounts_services as services
from shared.usecases.result import Failure


def list_roles(session: SnakeSession) -> list[Role]:
    """Every role in the system."""
    return selectors.list_roles(session)


def roles_of_user(session: SnakeSession, user_id: int) -> list[Role]:
    """A user's roles (through the UserRole bridge table)."""
    return selectors.roles_of_user(session, user_id)


def create_role(session: SnakeSession, name: str) -> Role | Failure:
    """Creates a role; `missing_fields` if the name comes in empty."""
    if not name:
        return Failure("missing_fields")
    role = services.create_role(session, name)
    session.commit()
    return role


def assign_role(
    session: SnakeSession, user_id: int, role_id: int
) -> UserRole | Failure:
    """Assigns a role to a user; `not_found` if the role does not exist."""
    if selectors.get_role(session, role_id) is None:
        return Failure("not_found")
    link = services.assign_role(session, user_id, role_id)
    session.commit()
    return link


def revoke_role(session: SnakeSession, user_id: int, role_id: int) -> None | Failure:
    """Removes a role from a user; `not_found` if that assignment did not exist."""
    if not services.revoke_role(session, user_id, role_id):
        return Failure("not_found")
    session.commit()
    return None
