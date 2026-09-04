"""Django and SnakeORM name the SAME database, and under `manage.py test` it is this run's own.

WHY THIS FILE EXISTS. There are two resolvers for one name in this demo, and there always have been:
`config/settings.py` builds `DATABASES["default"]["NAME"]` for Django, and `shared/config.py` builds
it again for SnakeORM. They read the same `.env` variable, so for a long time they could not disagree
and nobody needed a net. Giving a test run a database of its own changed that: the name is now the
variable PLUS a derived session id, and a derived value is a thing two resolvers can derive
differently.

WHAT DISAGREEING WOULD LOOK LIKE, and it is the worst shape a bug takes here: both halves keep
working. Django writes its sessions and its migrations into one database, SnakeORM writes the domain
into another, every request answers 200 and the pages come back empty. That exact failure is already
recorded in `shared/config.py`, from the time the connection was built twice: "each half worked, and
together they did nothing".

`SimpleTestCase` because nothing here touches data — it compares two strings that were computed
before any of this ran.
"""

from __future__ import annotations

from django.conf import settings
from django.test import SimpleTestCase

from shared.config import connection_config
from shared.session import MARK, current


class DjangoAndTheOrmShareOneDatabase(SimpleTestCase):
    """The two resolvers, held against each other."""

    def test_django_and_snakeorm_point_at_the_same_database(self) -> None:
        """Django's `NAME` is exactly the one `shared.config` hands SnakeORM.

        On Postgres and MySQL that is a database name; on SQLite it is a file path, and the
        comparison is the same either way because `connection_config` answers with whichever the
        engine uses. The SQLite case is the one that would break first: the file name has no
        environment variable behind it, so it is the half where the two resolvers have the least
        holding them together.
        """
        self.assertEqual(
            settings.DATABASES["default"]["NAME"],
            connection_config("django").name,
            "Django and SnakeORM are pointed at two different databases. Both halves will keep "
            "working — Django writing sessions and migrations into one, the domain going into the "
            "other — and every page will answer 200 with nothing on it.",
        )

    def test_the_test_run_has_a_database_of_its_own(self) -> None:
        """Under `manage.py test` the name carries this run's session id.

        Without it, two people running this suite at once are dropping and recreating each other's
        twenty-nine tables. The seed is deterministic, so the counts usually still add up and both
        runs go green over a schema that has moved underneath them — which is the quiet version of
        the `DuplicateTable` this repository has already met in its loud one.

        It also pins the half of `manage.py` that is easy to lose: the claim happens only for `test`,
        and only before `config.settings` is imported. Move either and this goes red instead of
        silently going back to the shared database.
        """
        session = current()

        self.assertIsNotNone(
            session,
            "this run has no session id, so `manage.py test` did not claim one before importing "
            "settings and the suite is on the database every other run shares.",
        )
        self.assertIn(f"{MARK}{session}", str(settings.DATABASES["default"]["NAME"]))
