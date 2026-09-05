"""Code shared by the three demo apps (Django/Flask/FastAPI).

The SINGLE source of truth: the seed data (`constants`), the SnakeORM models (`models`), the password
hashing (`auth`) and the `.env` config that picks SQLite or PostgreSQL (`config`). Defined once and
reused by the three frameworks; each one only writes its own seeder and its own routes.
"""
