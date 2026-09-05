"""Introspection: how a database's schema is READ (the third axis, alongside `dialects` and `drivers`).

It returns the SAME graph as the Model Compiler: scaffolding and drift detection compare with no intermediate format.
"""

from snakeorm.introspection.mysql import MySQLIntrospector as MySQLIntrospector
from snakeorm.introspection.base import SnakeIntrospector as SnakeIntrospector
from snakeorm.introspection.drift import drift as drift
from snakeorm.introspection.models import SnakeMirrorNames as SnakeMirrorNames
from snakeorm.introspection.models import render_models as render_models
from snakeorm.introspection.models import unrepresentable as unrepresentable
from snakeorm.introspection.postgres import PostgresIntrospector as PostgresIntrospector
from snakeorm.introspection.sqlite import SQLiteIntrospector as SQLiteIntrospector
