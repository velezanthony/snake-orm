# Release process

!!! warning "This process has never been executed"

    `git tag` returns nothing: **zero tags, zero published versions**. Everything below is the
    intended procedure, not a routine somebody has run. Before the first release there is a list of
    blockers in [What is missing before the first release](#what-is-missing-before-the-first-release),
    and none of them is optional.

```bash
make audit                 # everything green first
uv build                   # produces dist/*.whl and dist/*.tar.gz
unzip -l dist/*.whl        # check: only snakeorm/ (+ py.typed)
uv publish                 # publish (or: twine upload dist/*)
git tag vX.Y.Z && git push --tags
```

The package is built as a Python wheel with [hatchling](https://hatch.pypa.io/). `make audit` is the
local gate, and what it demands is in [Testing](testing.md).

## The distribution name is not `snakeorm`

`pyproject.toml` declares `name = "laboratorio-snake-orm"`. `snakeorm` is only the **import name**
(`packages = ["src/snakeorm"]` under `[tool.hatch.build.targets.wheel]`).

So today `uv publish` would publish a project called `laboratorio-snake-orm` on PyPI, installed with
`pip install laboratorio-snake-orm` and imported as `import snakeorm`. That split is legal and
common, but it is a decision, not an accident to discover at upload time. Whoever runs the first
release has to either claim `snakeorm` on PyPI and rename the project, or accept the current name
and say so in the README.

## Versioning

SemVer (`MAJOR.MINOR.PATCH`), in `pyproject.toml` (`project.version`).

- **PATCH** — fixes with no API change.
- **MINOR** — new backward-compatible functionality.
- **MAJOR** — incompatible changes to the public API (`snakeorm/__init__.py`).

The current version is **`0.1.0`**, which means those rules do not apply as written yet. Under
SemVer, everything before `1.0.0` is the initial development phase: the public API is not stable and
a breaking change goes out in a MINOR bump (`0.1.0` → `0.2.0`), because there is no MAJOR to spend
without declaring the API stable. The rules above start being literal from `1.0.0`, and moving to
`1.0.0` is a commitment about `snakeorm/__init__.py` — the surface `test/test_public_api.py`
derives — not a milestone of feature count.

## What travels in the wheel

The `src/` layout guarantees that **only the package is packaged**: `test/`, `benchmarks/` and
`examples/` do NOT enter. Check it with `unzip -l dist/*.whl`.

The `py.typed` marker (`src/snakeorm/py.typed`) is critical: it makes the CONSUMER's mypy/pyright
recognize the ORM's types (PEP 561). Without it, `import snakeorm` would yield `Any` — exactly what
the project promises not to do.

## What is missing before the first release

Verified against the repo, not assumed:

- **No publish job.** `.github/workflows/` contains exactly two files: `ci.yml` (gates) and
  `docs.yml` (publishes to GitHub Pages). Neither runs `uv build` or `uv publish`, there is no
  `on: release` trigger and no PyPI secret configured. The entire process is manual, from a laptop.

## Steps

1. `make audit` green (lint, format, types, docs, tests).
2. Bump the version in `pyproject.toml`.
3. Write the `CHANGELOG.md` entry, under a version heading instead of `Unreleased`. It is in
   English only, and the file says why in its own opening lines.
4. `uv build`.
5. Verify the wheel (`unzip -l`: only `snakeorm/` + `py.typed`).
6. `uv publish` (or `twine upload dist/*`) — check first which distribution name you are pushing.
7. `git tag vX.Y.Z && git push --tags`. This would be the first tag in the repository.

## CI

`.github/workflows/ci.yml` runs on every push to `main` and every pull request, in four jobs — the
same ones you can run locally from [Development setup](development.md):

- **`quality`** (that is its name in the YAML, not a translated one) — ruff, `ruff format --check`,
  `mypy .`, `mypy shared` from `frameworks/`, `mypy --strict src/snakeorm/`, `pyright src/snakeorm/`
  and `pyright` over the three demo apps. That last step is the one easiest to leave out of a list
  written by hand, and it is here because it already was left out once. It goes first and without a
  matrix on purpose: if there is a lint or type error, there is no point in raising one Postgres per
  leg of the `tests` matrix to find out.
- **`tests`** — the full matrix, Python 3.11–3.14 × PostgreSQL/SQLite: the whole cartesian product
  with no `exclude`, because a version tested only against SQLite is a version you do not know talks
  to Postgres. MariaDB runs alongside for the MySQL e2e. `if` does not exist at the `services:`
  level, so the Postgres container is brought up on the SQLite leg as well — a few wasted seconds
  against duplicating the job, which would go out of sync the first time round. The postgres leg sets
  `SNAKEORM_REQUIRE_POSTGRES=true`, which turns a skip for lack of a database into a failure, and
  measures coverage.
- **`frameworks`** — the three demo apps plus the shared layer, as a four-leg matrix (`shared`,
  `fastapi`, `flask`, `django`) with `fail-fast: false`. This one gates too, and it is the only
  place where the pipeline is exercised end to end.
- **`docs`** — `mkdocs build --strict`, where any warning is an error.

`docs.yml` is separate: it publishes to GitHub Pages on pushes to `main` that touch `docs/`,
`mkdocs.yml` or the workflow itself. It publishes documentation, never a package.

A release should not go out with CI red.
