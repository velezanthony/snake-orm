"""Multi-tenancy shape: a row belongs to an organisation THROUGH the memberships of its owner.

    Contract --owner--> User --memberships--> Membership --organization--> Organization

The existing domains cannot express the defect this exists for. `deep_domain` reaches a collection
from a to-one only as `Truck.maker.trucks`, where the child of the subquery IS the root table: an
emitter that correlated against the wrong end would still name `trucks`, and the reader has to
decide whether two aliases over one table mean what they should. Here the three tables are
different, so the correlation either reaches the JOINed user or it does not.

The tables are in the global registry, like every other scenario domain, because the cross-engine
harness builds its DDL from it; the names are uncommon so they collide with nobody.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.drivers import SnakeDriver
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.model import SnakeModel


@snake_model(table="tenancy_organizations")
class Organization(SnakeModel):
    """The tenant. The far end of the predicate that decides who owns a row."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    memberships: SnakeToMany[Membership] = snake_to_many("organization")


@snake_model(table="tenancy_users")
class User(SnakeModel):
    """The owner of a contract, and the holder of the memberships."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    display_name: SnakeColumn[str] = snake_str()
    memberships: SnakeToMany[Membership] = snake_to_many("user")


@snake_model(table="tenancy_memberships")
class Membership(SnakeModel):
    """A user in an organisation, with the role they hold there."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    role: SnakeColumn[str] = snake_str()
    user_id: SnakeColumn[int] = snake_int()
    organization_id: SnakeColumn[int] = snake_int()
    user: SnakeToOne[User] = snake_to_one(user_id)
    organization: SnakeToOne[Organization] = snake_to_one(organization_id)


@snake_model(table="tenancy_contracts")
class Contract(SnakeModel):
    """The row whose tenant is not written on it: it is reached through its owner."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    alias: SnakeColumn[str] = snake_str()
    owner_id: SnakeColumn[int] = snake_int()
    owner: SnakeToOne[User] = snake_to_one(owner_id)


MODELS = (Organization, User, Membership, Contract)
"""Creation order: a table before whoever points at it."""


def seed(driver: SnakeDriver) -> None:
    """Two organisations, three users, and one contract each for three different tenancy answers.

    Ada belongs to both organisations, Linus only to Globex and Grace to none. The user ids and the
    organisation ids are deliberately NOT parallel, so a correlation wired to the wrong column is
    caught by the rows as well as by the SQL.
    """
    rows = (
        "INSERT INTO tenancy_organizations VALUES (10, 'Acme'), (20, 'Globex')",
        "INSERT INTO tenancy_users VALUES (1, 'Ada'), (2, 'Linus'), (3, 'Grace')",
        "INSERT INTO tenancy_memberships VALUES"
        " (100, 'OWNER', 1, 10), (101, 'MEMBER', 1, 20), (102, 'MEMBER', 2, 20)",
        "INSERT INTO tenancy_contracts VALUES"
        " (1000, 'ada-1', 1), (1001, 'linus-1', 2), (1002, 'grace-1', 3)",
    )
    for statement in rows:
        driver.execute(statement, ())
    driver.commit()
