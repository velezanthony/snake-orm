"""accounts domain — SELECTORS: reads of roles and of a user's roles (N—N through `UserRole`).

Every framework re-exports them from `apps/accounts/selectors.py`.

Each read comes in TWO pieces, and the split is the seam the asynchronous demo stands on. The
FRAGMENT builds a `SnakeQuery` and does not run it; the EXECUTOR takes a session and runs it. Only
the executor has a colour — `session.all(...)` on one path, `await session.all(...)` on the other —
so the SQL, which is the part that drifts when it is written twice, is written once and shared by
both. See `shared/aio/accounts_usecases.py` for the other half.
"""

from __future__ import annotations

from snakeorm import SnakeQuery, SnakeSession

from shared.models import Role, UserRole


def all_roles() -> SnakeQuery[Role]:
    """FRAGMENT: every role, by name."""
    return SnakeQuery(Role).order_by(Role.name.asc())


def role_by_id(role_id: int) -> SnakeQuery[Role]:
    """FRAGMENT: one role by id."""
    return SnakeQuery(Role).filter(Role.id == role_id)


def assignment(user_id: int, role_id: int) -> SnakeQuery[UserRole]:
    """FRAGMENT: the bridge row that grants ONE role to ONE user, if it is there.

    It lives here and not in the service that deletes it because it is a read, and because the
    asynchronous twin of that service needs the very same one: a revoke is "find the link, delete
    the link", and the finding half is this.
    """
    return SnakeQuery(UserRole).filter(
        UserRole.user_id == user_id, UserRole.role_id == role_id
    )


def list_roles(session: SnakeSession) -> list[Role]:
    """Every role, by name."""
    return session.all(all_roles())


def get_role(session: SnakeSession, role_id: int) -> Role | None:
    """A role by id, or `None`."""
    return session.first(role_by_id(role_id))


def roles_of(user_id: int) -> SnakeQuery[Role]:
    """FRAGMENT: a user's roles, NOT executed: more can still be stacked on top.

    A SUBQUERY over the bridge, not two round trips: `as_scalar` projects the `role_id` filtered by
    user and `Role.id.in_(sub)` consumes it. Same as `taxonomy_selectors.tags_of`, and for the same
    reason: the second round trip carried a list of ids that grows with the data.
    """
    bridged = (
        SnakeQuery(UserRole)
        .filter(UserRole.user_id == user_id)
        .as_scalar(UserRole.role_id)
    )
    return SnakeQuery(Role).filter(Role.id.in_(bridged))


def roles_of_user(session: SnakeSession, user_id: int) -> list[Role]:
    """The roles assigned to a user, by name. Executes what `roles_of` composes."""
    return session.all(roles_of(user_id).order_by(Role.name.asc()))
