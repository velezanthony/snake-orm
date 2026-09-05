"""BASIC benchmark harness for SnakeORM against a real Postgres.

It measures the ORM's own operations (compilation, SQL emission, INSERT, simple and deep SELECT,
to-many include and aggregates) and prints clear timings. It does NOT compare against other ORMs:
it is our own reproducible baseline. Run it with `uv run python -m benchmarks.run`.
"""
