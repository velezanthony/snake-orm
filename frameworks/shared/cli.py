"""Seeding CLI: creates the schema and populates a demo at the requested scale, WITHOUT starting the server.

    python -m shared.cli <framework> <scale>

- `framework`: `flask` | `django` | `fastapi` (picks which demo DB to seed).
- `scale`:     `minimal` | `normal` | `large` | `massive` (data size).

Argument validation has TWO layers: `argparse` with `choices` rejects any value outside the list (clear
message + exit code 2), and underneath `shared.data.seed` only accepts a `Scale` from the enum. That way
"create a massive one" is a reproducible command with validation, not a loose environment variable set
when starting the server.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from snakeorm import SnakeQuery, count, snake_table

from shared import config
from shared.data import Scale, seed
from shared.models import MODELS

# The three demos whose DB `shared.config` knows how to set up (by framework name).
_FRAMEWORKS = ("flask", "django", "fastapi")


def _scale_names() -> list[str]:
    """Lowercase scale names, for argparse's `choices` (`minimal`, `normal`, …)."""
    return [scale.name.lower() for scale in Scale]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: validates the arguments, recreates the schema and seeds. Returns the exit code."""
    parser = argparse.ArgumentParser(
        prog="shared.cli", description="Seeds a SnakeORM demo at a given scale."
    )
    parser.add_argument(
        "framework", choices=_FRAMEWORKS, help="which demo and database to seed"
    )
    parser.add_argument("scale", choices=_scale_names(), help="how much data to write")
    args = parser.parse_args(argv)

    scale = Scale[args.scale.upper()]
    spec = scale.spec
    print(
        f"Sembrando '{args.framework}' a escala {scale.name} "
        f"(~{spec.users} users, {spec.posts} posts, {spec.visits} visits)…",
        flush=True,
    )

    config.init_schema(args.framework)
    session = config.make_session(args.framework)
    try:
        start = time.perf_counter()
        seed(session, scale)
        elapsed = time.perf_counter() - start
        total = sum(
            session.select(SnakeQuery(model), count())[0][0] for model in MODELS
        )
        print(
            f"Done in {elapsed:.1f}s: {total} rows in {len(MODELS)} tablas.",
            flush=True,
        )
        for model in MODELS:
            rows = session.select(SnakeQuery(model), count())[0][0]
            print(f"  {snake_table(model).name:16} {rows}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
