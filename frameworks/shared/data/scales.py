"""Data scales for the seeder, in the style of generating data at different sizes.

A `Scale` fixes the count of the PRIMARY entities (users, blogs, posts, comments, visits, tags,
skus, orders, deliveries); the remaining tables (categories, revisions, attachments, reactions, roles, sessions,
tokens, subscriptions, invoices, payments, post_tags, warehouse_stock, stock_movements, order_lines,
depots, packaging_units)
are DERIVED by the factory with fixed ratios. That way the whole volume goes up or down by moving a
single constant.

`visits` is the VOLUME table (the one that reaches millions): it is what shows off pagination and
traffic aggregates without the other tables blowing up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True, slots=True)
class ScaleSpec:
    """Counts of a scale's primary entities. The secondary ones are derived by the factory."""

    users: int
    blogs: int
    posts: int
    comments: int
    visits: int
    tags: int
    skus: int
    """Stockable items. The stock rows are DERIVED: half the catalogue in each warehouse, so this
    number decides how wide the composite-key table gets — four warehouses times skus/2."""

    orders: int
    """Customer orders. Their lines are DERIVED at one to three per order, picked from what the
    order's own warehouse actually stocks — so this number decides the size of the SECOND
    composite-key table, and the ratio never lets it outgrow the stock it points at."""

    deliveries: int
    """Deliveries booked out of a depot. The depots and the box sizes are FIXED catalogues — four and
    three — because both are facts about the world rather than volume, so this is the only knob the
    logistics domain has.

    It stays SMALL relative to `visits`, and on purpose: the load page reads a window over these rows
    and a window is where a table of millions stops being a demo and starts being a wait. What the
    domain shows off is the SHAPE of the frame, and a hundred bookings show it exactly as well as a
    million would."""


class Scale(Enum):
    """Data sizes, from toy to stress. The value is the `ScaleSpec` with the counts."""

    MINIMAL = ScaleSpec(
        users=8,
        blogs=3,
        posts=15,
        comments=40,
        visits=150,
        tags=8,
        skus=10,
        orders=12,
        deliveries=12,
    )
    NORMAL = ScaleSpec(
        users=60,
        blogs=10,
        posts=300,
        comments=2_000,
        visits=20_000,
        tags=20,
        skus=80,
        orders=150,
        deliveries=120,
    )
    LARGE = ScaleSpec(
        users=500,
        blogs=40,
        posts=4_000,
        comments=40_000,
        visits=400_000,
        tags=40,
        skus=600,
        orders=1_500,
        deliveries=800,
    )
    MASSIVE = ScaleSpec(
        users=2_000,
        blogs=120,
        posts=25_000,
        comments=300_000,
        visits=3_000_000,
        tags=60,
        skus=4_000,
        orders=12_000,
        deliveries=4_000,
    )

    @property
    def spec(self) -> ScaleSpec:
        """This scale's `ScaleSpec` (sugar so `.value` is not written all over the place)."""
        return self.value


def scale_by_name(name: str) -> Scale:
    """Resolves a scale by name (`"minimal"`, `"normal"`, …), case-insensitively."""
    try:
        return Scale[name.strip().upper()]
    except KeyError as exc:
        options = ", ".join(scale.name.lower() for scale in Scale)
        raise ValueError(f"Unknown scale: {name!r}. Options: {options}.") from exc


def demo_scale() -> Scale:
    """The demos' scale, taken from `DEMO_SCALE` (default `normal`): that way the panel has volume
    without touching code. `DEMO_SCALE=minimal` speeds up boot; `large`/`massive` put it under stress."""
    return scale_by_name(os.environ.get("DEMO_SCALE", "normal"))
