"""`manage.py snakeorm ...` — the SnakeORM CLI, reachable the way Django taught you.

One line, and deliberately one line: Django requires the file to sit at this path with a class
called `Command`, and everything else lives in the ORM. An adapter that grew logic here would be a
second place to keep in step with the core parser.
"""

from snakeorm.cli.hooks import SnakeOrmCommand as Command

__all__ = ["Command"]
