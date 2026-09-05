"""SnakeORM's SQL dialects: how the SQL is written for each engine."""

from snakeorm.dialects.base import SnakeDialect as SnakeDialect
from snakeorm.dialects.mysql import MySQLDialect as MySQLDialect
from snakeorm.dialects.postgres import PostgresDialect as PostgresDialect
from snakeorm.dialects.sqlite import SQLiteDialect as SQLiteDialect
