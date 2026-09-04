"""accounts domain — SERVICES: create roles and assign/revoke them to users.

Every framework re-exports them from `apps/accounts/services.py`.
"""

from __future__ import annotations

from snakeorm import SnakeSession

from shared.models import Role, UserRole
from shared.selectors.accounts_selectors import assignment


def create_role(session: SnakeSession, name: str) -> Role:
    """Creates a role."""
    return session.add(Role(name=name))


def assign_role(session: SnakeSession, user_id: int, role_id: int) -> UserRole:
    """Assigns a role to a user (creates the link in `UserRole`)."""
    return session.add(UserRole(user_id=user_id, role_id=role_id))


def revoke_role(session: SnakeSession, user_id: int, role_id: int) -> bool:
    """Revokes a role from a user. `False` if they did not have it.

    The look-up goes through the `assignment` fragment rather than an inline query, so that the
    asynchronous twin deletes the row it found with the SAME `WHERE` and not with a second one that
    happens to look alike today.
    """
    link = session.first(assignment(user_id, role_id))
    if link is None:
        return False
    session.delete(link)
    return True
