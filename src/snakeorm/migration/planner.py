"""Migration apply order BY FK DEPENDENCY: the one creating a table goes BEFORE the one referencing
it.

The dependency is DERIVED from the FKs (the `target_table` serialised into the migration), NOT
declared by hand as in Django. It exists for PER-DOMAIN migrations (several directories, each
numbering from `0001`): all of them are loaded and ordered so that `accounts` (which creates `users`)
comes before `blog` (which references it), and so on. A reference to a table that no migration in the
set creates (it already exists) imposes no order.
"""

from __future__ import annotations

from snakeorm.core.exceptions import SnakeMigrationError
from snakeorm.metadata import SnakeRelationshipKind
from snakeorm.migration.operations import CreateTable
from snakeorm.migration.runner import Migration


def _created(migration: Migration) -> set[str]:
    """Tables this migration CREATES."""
    return {op.table.name for op in migration.operations if isinstance(op, CreateTable)}


def _referenced(migration: Migration) -> set[str]:
    """Tables the FKs of this migration REFERENCE (by `target_table`, without the schema).

    Only TO_ONE counts: it is this table that CARRIES the FK, so it depends on the target. A TO_MANY is
    the INVERSE relation (the FK lives in the other table), so it imposes NO dependency here — counting
    it would introduce cycles (accounts.User.posts <-> blog.Post.author).
    """
    refs: set[str] = set()
    for op in migration.operations:
        if isinstance(op, CreateTable):
            for relationship in op.table.relationships:
                if (
                    relationship.kind is SnakeRelationshipKind.TO_ONE
                    and relationship.target_table
                ):
                    refs.add(relationship.target_table.rpartition(".")[2])
    return refs


def dependency_order(migrations: list[Migration]) -> list[Migration]:
    """Orders migrations so each one comes AFTER those creating the tables it references.

    DFS with cycle detection; stable output (it starts in version order). References to tables that no
    migration in the set creates (already existing ones) impose no order.
    """
    creator: dict[str, Migration] = {}
    for migration in migrations:
        for table in _created(migration):
            creator[table] = migration

    ordered: list[Migration] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(migration: Migration) -> None:
        if migration.version in visited:
            return
        if migration.version in visiting:
            raise SnakeMigrationError(
                f"Dependency cycle among migrations: '{migration.version}' depends (through an "
                f"FK, directly or indirectly) on itself. Review the cross-domain relationships."
            )
        visiting.add(migration.version)
        created = _created(migration)
        for ref in sorted(_referenced(migration)):
            target = creator.get(ref)
            if target is not None and ref not in created:
                visit(target)
        visiting.discard(migration.version)
        visited.add(migration.version)
        ordered.append(migration)

    for migration in sorted(migrations, key=lambda m: m.version):
        visit(migration)
    return ordered
