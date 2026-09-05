"""accounts domain (roles), asked of an `AsyncSession`. The twin of `shared/usecases/accounts_usecases.py`.

Same names, same parameters, same answers — including the same `Failure` reasons, because a reason
is what the user reads and two wordings of one refusal is the drift this package's nets exist to
catch. What differs is one keyword per statement.

The queries are NOT rebuilt here: `all_roles`, `role_by_id` and `assignment` come from the
synchronous selectors, unchanged, because a `SnakeQuery` has no colour. That is why the SQL of this
module and of its twin is identical by construction rather than by agreement.
"""

from __future__ import annotations

from snakeorm import AsyncSession

from shared.models import Role, UserRole
from shared.selectors.accounts_selectors import (
    all_roles,
    assignment,
    role_by_id,
    roles_of,
)
from shared.usecases.result import Failure


async def list_roles(session: AsyncSession) -> list[Role]:
    """Every role in the system."""
    return await session.all(all_roles())


async def roles_of_user(session: AsyncSession, user_id: int) -> list[Role]:
    """A user's roles (through the UserRole bridge table), by name."""
    return await session.all(roles_of(user_id).order_by(Role.name.asc()))


async def create_role(session: AsyncSession, name: str) -> Role | Failure:
    """Creates a role; `missing_fields` if the name comes in empty."""
    if not name:
        return Failure("missing_fields")
    role = await session.add(Role(name=name))
    await session.commit()
    return role


async def assign_role(
    session: AsyncSession, user_id: int, role_id: int
) -> UserRole | Failure:
    """Assigns a role to a user; `not_found` if the role does not exist."""
    if await session.first(role_by_id(role_id)) is None:
        return Failure("not_found")
    link = await session.add(UserRole(user_id=user_id, role_id=role_id))
    await session.commit()
    return link


async def revoke_role(
    session: AsyncSession, user_id: int, role_id: int
) -> None | Failure:
    """Removes a role from a user; `not_found` if that assignment did not exist."""
    link = await session.first(assignment(user_id, role_id))
    if link is None:
        return Failure("not_found")
    await session.delete(link)
    await session.commit()
    return None
