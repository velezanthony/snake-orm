"""The one trigger in the demos, and the reason it is a trigger and not a use case.

`Post.visit_count` is denormalised. Counting `visits` is the honest query and it is the one that does
not scale — the volume table carries millions of rows, so a listing of twenty posts would pay twenty
`COUNT`s or one `GROUP BY` over the lot.

WHY THE ENGINE KEEPS IT AND NOT THE ORM. The rule this project gives for reaching a trigger is that
the invariant has to hold ALWAYS, including for writes that never pass through Python: the seeder, a
`session.raw`, a psql session, another service. A use case that bumped the counter would be correct
until the first writer that forgot, and nothing would say so — the number would just drift.

AND IT IS ALSO WHERE `refresh` LIVES, because this is the only place in the demos where the
database changes a row UNDERNEATH somebody holding it. `record_visit` reads the post before the
write, the trigger bumps its counter during the commit, and the object in Python is then out of date
by one — a number no code here is in a position to work out, since two visits landing at once make
any increment in Python a guess. Reading it back with a second query would answer correctly and leave
TWO objects for one post, free to disagree with each other for as long as both are alive. That is the
question `session.refresh(post)` exists for, and a `refresh` of a row nobody else touched would prove
none of it.

WHAT THIS FILE ASSERTS, AND WHY IT IS THE HARD HALF. That the counter matches a real `COUNT` after
rows are inserted WITHOUT the ORM being told about the counter at all. Nothing here calls anything
that mentions `visit_count`: the assertion is that the DATABASE did it.

AND IT IS WHERE THE THIRD SPELLING WAS FOUND. Running this against SQLite is what produced `near
"UPDATE": syntax error` and revealed that SQLite needs `BEGIN`/`END` around a trigger body — after
PostgreSQL had already shown it needs a function. Three engines, three spellings, one declaration.
"""

from __future__ import annotations

from collections import Counter

from snakeorm import SnakeQuery, SnakeSession, SnakeUtc
from snakeorm.migration import emit_create_trigger

from shared.models import Post, Visit
from shared.models.engagement_models import visit_counter
from shared.usecases import engagement_usecases as usecases
from shared.usecases.result import Failure


def _install_the_trigger(session: SnakeSession) -> None:
    """Creates the declared trigger on the session's engine, as a migration would.

    The conftest builds the schema from the MODELS, which knows nothing about triggers — they live in
    the registry, not in a table. So the one under test is installed here, through the same emitter a
    migration uses, which is what keeps this test measuring the real thing.
    """
    for statement in emit_create_trigger(visit_counter, session.dialect):
        session._driver.execute(statement, ())  # noqa: SLF001 - the harness has no public hook
    session.commit()


def _visit(session: SnakeSession, post_id: int) -> None:
    """One page view, inserted the ordinary way. Nothing here mentions the counter."""
    session.add(
        Visit(
            post_id=post_id, ip="127.0.0.1", user_agent=None, visited_at=SnakeUtc.now()
        )
    )
    session.commit()


def test_the_counter_matches_a_real_count(seeded: SnakeSession) -> None:
    """After N visits, the denormalised number equals the number of rows. The engine did it."""
    _install_the_trigger(seeded)
    post = seeded.all(SnakeQuery(Post).limit(1))[0]
    before = post.visit_count

    for _ in range(3):
        _visit(seeded, post.id)

    again = seeded.all(SnakeQuery(Post).filter(Post.id == post.id))[0]
    assert again.visit_count == before + 3


def test_it_counts_the_right_post(seeded: SnakeSession) -> None:
    """A counter that goes up on every row is not a counter, it is a total.

    The trigger filters by `NEW.post_id`, and this is what would catch that filter being dropped —
    the sum would still be right and every individual number would be wrong.
    """
    _install_the_trigger(seeded)
    first, second = seeded.all(SnakeQuery(Post).limit(2))
    start = {first.id: first.visit_count, second.id: second.visit_count}

    _visit(seeded, first.id)
    _visit(seeded, first.id)
    _visit(seeded, second.id)

    rows = {
        row.id: row.visit_count
        for row in seeded.all(
            SnakeQuery(Post).filter(Post.id.in_([first.id, second.id]))
        )
    }
    assert rows[first.id] == start[first.id] + 2
    assert rows[second.id] == start[second.id] + 1


def test_the_declaration_reaches_the_registry(seeded: SnakeSession) -> None:
    """`snake_trigger()` registers it, which is the half a hand-built `SnakeTriggerInfo` skips.

    It is also the path a migration reads: the drift check compares the registry against the history,
    so a trigger declared and not migrated turns that check red. Without this line, the declaration
    could stop registering and only the drift check would notice — one storey away from here.
    """
    from snakeorm import registry  # noqa: PLC0415 - only this test needs it

    declared = {(trigger.table, trigger.name) for trigger in registry.triggers()}

    assert ("visits", "tg_bump_visit_count") in declared


def test_a_count_over_the_volume_table_agrees_with_every_counter(
    seeded: SnakeSession,
) -> None:
    """The invariant stated over the whole seeded set, which is what a report would trust.

    The counters start at whatever the seed left them and the trigger maintains them from there, so
    what is compared is the DELTA: every post's counter moves by exactly the visits added.
    """
    _install_the_trigger(seeded)
    posts = seeded.all(SnakeQuery(Post).limit(5))
    start = {post.id: post.visit_count for post in posts}
    added = Counter({posts[0].id: 2, posts[1].id: 1, posts[3].id: 4})

    for post_id, times in added.items():
        for _ in range(times):
            _visit(seeded, post_id)

    rows = seeded.all(SnakeQuery(Post).filter(Post.id.in_(list(start))))
    assert {row.id: row.visit_count for row in rows} == {
        post_id: base + added.get(post_id, 0) for post_id, base in start.items()
    }


def test_recording_a_visit_reports_the_number_the_trigger_wrote(
    seeded: SnakeSession,
) -> None:
    """The operation answers with the counter as the DATABASE has it, not as Python guessed it.

    This is the honest shape of a `refresh`: the post is read BEFORE the write, the engine changes
    it during the commit, and the same instance is taught what the row now says. An increment done
    here would be right until two visits landed at once and would never say when it stopped being.
    """
    _install_the_trigger(seeded)
    post = seeded.all(SnakeQuery(Post).limit(1))[0]
    before = post.visit_count

    tally = usecases.record_visit(seeded, post.id, "127.0.0.1")

    assert not isinstance(tally, Failure)
    assert tally.visit_count == before + 1
    assert tally.visit.post_id == post.id


def test_the_refreshed_number_survives_a_second_visit(seeded: SnakeSession) -> None:
    """Twice in a row, so the answer is a reading and not a constant.

    A `refresh` that had been quietly replaced by `before + 1` would pass the test above and fail
    here the moment the counter moved twice — which is the cheapest way to tell a reading from an
    arithmetic that happens to agree once.
    """
    _install_the_trigger(seeded)
    post = seeded.all(SnakeQuery(Post).limit(1))[0]
    before = post.visit_count

    first = usecases.record_visit(seeded, post.id, "127.0.0.1")
    second = usecases.record_visit(seeded, post.id, "127.0.0.2")

    assert not isinstance(first, Failure)
    assert not isinstance(second, Failure)
    assert (first.visit_count, second.visit_count) == (before + 1, before + 2)


def test_there_is_ONE_object_for_the_post_and_it_is_the_refreshed_one(
    seeded: SnakeSession,
) -> None:
    """The instance held before the write is the instance that learns, which is why it is a refresh.

    Re-querying would answer the same number and hand back a SECOND object for one row. Nothing
    would fail — until two parts of a handler held one post and disagreed about it.
    """
    _install_the_trigger(seeded)
    post = seeded.all(SnakeQuery(Post).limit(1))[0]

    tally = usecases.record_visit(seeded, post.id, "127.0.0.1")
    seeded.refresh(post)

    assert not isinstance(tally, Failure)
    assert post.visit_count == tally.visit_count


def test_a_visit_to_a_post_that_is_not_there_is_refused(seeded: SnakeSession) -> None:
    """`not_found`, and it is the read BEFORE the write that answers it.

    The post has to be loaded anyway — it is the object the refresh will teach — so the existence
    check costs nothing extra. Without it the insert would go to the engine and come back as a
    foreign key violation, which is a 500 where the honest answer is a 404.
    """
    _install_the_trigger(seeded)

    assert usecases.record_visit(seeded, 999_999, "127.0.0.1") == Failure("not_found")
