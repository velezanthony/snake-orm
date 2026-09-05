"""How a table is named in the SQL: `"schema"."table"` or just `"table"`.

Centralised because twenty-five call sites build it. SQLite has no named schemas (a `"public"."x"`
gives `unknown database "public"`), so qualifying per engine has to live in ONE place.
"""

from __future__ import annotations

from snakeorm.dialects import SnakeDialect


def qualified(schema: str, name: str, dialect: SnakeDialect) -> str:
    """Table reference, qualified by schema ONLY if the engine has schemas.

    On an engine without schemas, qualifying is not cosmetic: it is invalid SQL.
    """
    if dialect.supports_schemas:
        return f"{dialect.quote_ident(schema)}.{dialect.quote_ident(name)}"
    return dialect.quote_ident(name)
