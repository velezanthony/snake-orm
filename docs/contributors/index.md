# For contributors

```bash
make sync    # uv sync --all-extras --all-groups: package, extras and every group
make audit   # the CI gate before any PR
```

The development side of SnakeORM.

## What the project covers

Fix this before another page contradicts it:

- **Three first-class engines**: PostgreSQL, MySQL/MariaDB and SQLite. They were built in that
  order and each one is a new file in `dialects/` and another in `drivers/`, never a refactor. A
  model written once runs on all three.
- **Sync AND async**, over the same colorless seam. Generating SQL does not execute anything, so it
  has no color: `AsyncDriver` and `AsyncSession` came in without rewriting the compiler or the
  dialect. Both sessions consume the SAME `Plan` and the same message catalogue.

That is the surface any change has to keep standing. Touching a dialect means checking the other
two; touching the session means checking both colors.

## Where to go

- **[Development environment](development.md)** — uv, devcontainer, database.
- **[Testing](testing.md)** — the suite, how to run it, and the CI gates.
- **[Architecture](architecture.md)** — the model → metadata → SQL pipeline.
- **[Internals](internals.md)** — where each feature's code lives, one by one.
- **[The demos](frameworks.md)** — the only place the ORM is exercised the way an application
  would exercise it, with a server in front and a real database.
- **[Release process](release.md)** — versioning, packaging, and publishing.

Before touching code, read the repo root's `CONTRIBUTING.md`: the project rules (Strict TDD, zero
`Any`, conventional commits) and the Pull Request workflow.
