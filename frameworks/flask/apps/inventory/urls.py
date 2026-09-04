"""SSR routes of the inventory domain: the taxonomy's pages over a COMPOSITE key.

Nine of them now. The five CRUD pages were the pilot; `report` and `export` are what phase 4
added, and they are the two that read the ORM rather than write it — five aggregate statements
on one page, and a single streamed statement on the other. `export` is the only route in this
module that does not render a template, because a CSV is a response and not a page: inventing
one would be inventing a screen nobody looks at to hold a file nobody reads in a browser.

The last two arrived with the questions nothing here could answer. `alerts` reads the low-stock
VIEW — what do I need to reorder — which had been reachable from `/api/` and from no screen; and
`warehouse` is the sheet of one shed with every movement of every line on it, which is the to-many
over a composite key finally having somewhere to be looked at.

The JSON API lives apart in `api.py` (flask-smorest). The blueprint here is `inventory` and the one
there is `inventory-api`, which is the convention the rest of the demo already follows —
`blog`/`blog-api`, `auth`/`auth-api`, `lab`/`lab-api`: a plain name is the pages, the `-api` suffix
is the JSON. The API blueprint used to hold the plain name, which worked only for as long as this
domain had no pages to collide with it.

**These pages need NO login, and that is a decision rather than an omission.** The blog gates its
CRUD because a post belongs to somebody: the ownership check is what `editable_post` exists to
exercise. A stock row belongs to nobody — it is identified by a warehouse and a SKU, not by a user —
so a login step here would gate the pages without testing one thing about the ORM, and would add a
register-then-log-in preamble to every test of the composite key. The demo gates what has an owner.

The views are THIN in the same sense as the blog's: they parse the request, call the layer below
with FLAT parameters and translate the result. The one difference is WHICH layer, and it matters —
a GET calls `viewmodels`, a POST calls `usecases`. That split is the point of the view-model layer:
a page hands the template a flat dict where every relation hop is already made, so no template of
this domain ever writes `stock.warehouse.code` and turns a render into a query.

Both halves of the key travel in the URL, always, in that order (`<warehouse_id>/<sku_id>`). Half a
key identifies nothing, and with a single warehouse seeded it would still find the right row — which
is how this domain breaks in front of somebody rather than in a test.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from shared.models import SkuKind

from apps.exports import csv_response
from apps.inventory import usecases, viewmodels
from apps.inventory.usecases import Failure

# The domain's PAGES. `-api` on the JSON one keeps the two apart in `url_for`.
inventory = Blueprint("inventory", __name__, url_prefix="/inventory")

# A resource `Failure` to its HTTP code. Only `not_found` reaches here: `missing_fields` goes back to
# the form it came from with a message, and `conflict` is the delete page's whole subject, so neither
# is an error page.
_STATUS_BY_REASON = {"not_found": 404}

# ONE sentence, said in two places: the confirmation page states it BEFORE the button is pressed, and
# the POST states it again for whoever got there past the page (a stale tab, a curl). It is a
# constant handed to the template rather than a paragraph written into it, because the same
# complaint phrased two ways is a drift this repo has already paid for once.
_CONFLICT_MESSAGE = (
    "That pair has movements, so it cannot be deleted: the movements are its audit trail "
    "and the foreign key refuses to orphan them."
)


def _render_failure(failure: Failure) -> tuple[str, int]:
    """Translate a resource `Failure` into the error page with the status its reason maps to."""
    return render_template("layout/error.html"), _STATUS_BY_REASON[failure.reason]


def _int_arg(name: str, default: int) -> int:
    """One integer out of the query string, falling back rather than raising.

    Every one of these arrives from a URL somebody may have typed, so `page=abc` is a page that does
    not exist and not a stack trace. The clamping of what a page number MEANS is not done here: the
    use case owns it, because only it knows how many pages there are.
    """
    return request.args.get(name, default=default, type=int) or default


def _int_field(name: str) -> int | None:
    """One integer out of the submitted form, or `None` when it is absent or is not a number.

    `None` and not `0`: a missing warehouse and warehouse number zero are different mistakes, and
    only the first one is the form posting back half a composite key.
    """
    raw = request.form.get(name, "").strip()
    try:
        return int(raw)
    except ValueError:
        return None


# ---- The five pages ----------------------------------------------------------------------------


@inventory.get("/list")
def list_stock() -> ResponseReturnValue:
    """The stock listing: a real page of rows, a warehouse filter and a pager. THREE statements.

    The three do not depend on how many rows come back, which is what makes the page's cost flat.
    `warehouse` narrows it and comes back in the view model so the `<select>` can mark its option;
    an unknown one narrows to nothing and the page says zero, because a filter that matches nothing
    is an answer.
    """
    warehouse_id = request.args.get("warehouse", default=None, type=int)
    page = viewmodels.stock_list(
        g.session, warehouse_id=warehouse_id, page=_int_arg("page", 1)
    )
    return render_template("inventory/list/inventory_list.html", **page)


@inventory.get("/detail/<int:warehouse_id>/<int:sku_id>")
def stock_detail(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """One pair in full: its row, the two to-one hops already made, and its movements. 404 if absent."""
    page = viewmodels.stock_detail(g.session, warehouse_id, sku_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("inventory/detail/inventory_detail.html", **page)


@inventory.get("/catalogue")
def stock_catalogue() -> ResponseReturnValue:
    """What the inventory is made OF: the warehouses and the SKUs a stock pair points at.

    Every other page here is about what is IN the inventory. Until this one existed neither of the
    two things a pair points at could be made from a page, so the demo could only stock what the
    seeder had built. TWO statements, and neither grows with the rows.
    """
    page = viewmodels.inventory_catalogue(g.session)
    return render_template(
        "inventory/catalogue/inventory_catalogue.html",
        **page,
        kinds=[kind.value for kind in SkuKind],
    )


@inventory.post("/catalogue/warehouses")
def create_warehouse() -> ResponseReturnValue:
    """POST: a new warehouse. `code` is THREE characters, fixed, and the ORM refuses a fourth.

    The refusal is worth reaching from a page: the ORM shouts rather than truncating, so a code of
    four letters comes back as something somebody can read instead of a row silently trimmed.
    """
    form = request.form
    try:
        opened_on = date.fromisoformat(form.get("opened_on", ""))
        shift_start = time.fromisoformat(form.get("shift_start", ""))
        cutoff = time.fromisoformat(form.get("cutoff", ""))
    except ValueError:
        flash("A warehouse needs an opening date, a shift start and a cutoff.", "error")
        return redirect(url_for("inventory.stock_catalogue"))
    code = form.get("code", "")
    if len(code) > 3:
        flash(
            "A warehouse code is three characters, fixed. The ORM refuses a fourth rather than "
            "trimming it in silence.",
            "error",
        )
        return redirect(url_for("inventory.stock_catalogue"))
    created = usecases.create_warehouse(
        g.session,
        code=code,
        name=form.get("name", ""),
        opened_on=opened_on,
        shift_start=shift_start,
        cutoff=cutoff,
    )
    if isinstance(created, Failure):
        flash("A warehouse needs a code and a name.", "error")
    else:
        flash("Opened.", "ok")
    return redirect(url_for("inventory.stock_catalogue"))


@inventory.post("/catalogue/skus")
def create_sku() -> ResponseReturnValue:
    """POST: a new SKU. The price is a `Decimal` and the lead time a `timedelta`, both from the form.

    Neither is a string by the time it reaches the use case, which is this layer's whole job: a price
    parsed as a float is the money bug this repository types its way out of.
    """
    form = request.form
    try:
        price = Decimal(form.get("price", ""))
        weight_kg = float(form.get("weight_kg", ""))
        lead_time_days = int(form.get("lead_time_days", ""))
        kind = SkuKind(form.get("kind", ""))
    except (ArithmeticError, ValueError):
        flash("A SKU needs a price, a weight, a lead time in days and a kind.", "error")
        return redirect(url_for("inventory.stock_catalogue"))
    created = usecases.create_sku(
        g.session,
        name=form.get("name", ""),
        kind=kind,
        price=price,
        weight_kg=weight_kg,
        lead_time=timedelta(days=lead_time_days),
    )
    if isinstance(created, Failure):
        flash("A SKU needs a name and a price above zero.", "error")
    else:
        flash("Created.", "ok")
    return redirect(url_for("inventory.stock_catalogue"))


@inventory.post("/catalogue/warehouses/<int:warehouse_id>/reserve")
def reserve_warehouse(warehouse_id: int) -> ResponseReturnValue:
    """POST: holds units across the warehouse's WHOLE stock, in ONE statement.

    It is here and not on a pair's page because it is not about a pair: it is one UPDATE over every
    row of the warehouse, which is the operation this demo has to be able to show.
    """
    units = _units_or_none(request.form.get("units"))
    if units is None:
        flash("How many units per pair? It has to be a number above zero.", "error")
        return redirect(url_for("inventory.stock_catalogue"))
    touched = usecases.reserve(g.session, warehouse_id=warehouse_id, units=units)
    if isinstance(touched, Failure):
        return _render_failure(touched)
    flash(f"Held units across {touched} row(s), in one statement.", "ok")
    return redirect(url_for("inventory.stock_catalogue"))


def _units_or_none(value: str | None) -> int | None:
    """A form field as a positive int, or `None` when it is missing, not a number, or not positive.

    Zero is refused here rather than passed on, and that is not the use case's rule duplicated: a
    movement of nothing is not a refusal to explain, it is a form somebody submitted empty.
    """
    try:
        units = int(value) if value is not None else None
    except ValueError:
        return None
    return units if units is not None and units > 0 else None


@inventory.post("/detail/<int:warehouse_id>/<int:sku_id>/receive")
def receive_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """POST: goods arrive into this pair. It creates the stock row if it was not there.

    It lives on the DETAIL page and not on one of its own, and that is the catalogue holding: a
    movement is something you do to the pair you are looking at, and its history is right there
    underneath. `orders` has an `operate` page because an operation there is something you go
    looking for; this is not that.
    """
    units = _units_or_none(request.form.get("units"))
    if units is None:
        flash("How many units arrived? It has to be a number above zero.", "error")
        return redirect(
            url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
        )
    received = usecases.receive(
        g.session, warehouse_id=warehouse_id, sku_id=sku_id, units=units
    )
    if isinstance(received, Failure):
        return _render_failure(received)
    flash("Received.", "ok")
    return redirect(
        url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
    )


@inventory.post("/detail/<int:warehouse_id>/<int:sku_id>/ship")
def ship_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """POST: goods leave this pair. It refuses BEFORE writing when there are not that many.

    The refusal is the half worth having a page for: shipping more than there is comes back refused
    with the pair unchanged, rather than as a negative row the CHECK would have caught three layers
    down with a driver error.
    """
    units = _units_or_none(request.form.get("units"))
    if units is None:
        flash("How many units left? It has to be a number above zero.", "error")
        return redirect(
            url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
        )
    shipped = usecases.ship(
        g.session, warehouse_id=warehouse_id, sku_id=sku_id, units=units
    )
    if isinstance(shipped, Failure):
        if shipped.reason == "not_found":
            return _render_failure(shipped)
        flash(
            "There are not that many on the shelf. Nothing was written — the refusal happens "
            "before the movement, not after a negative row.",
            "error",
        )
    else:
        flash("Shipped.", "ok")
    return redirect(
        url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
    )


@inventory.get("/create")
def new_stock_form() -> ResponseReturnValue:
    """The creation form: the two option lists, with no row in them (`is_update` is false)."""
    page = viewmodels.stock_form(g.session)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("inventory/create/inventory_create.html", **page)


@inventory.post("/create")
def create_stock() -> ResponseReturnValue:
    """Set the stock of a pair after a count. An UPSERT: it does not care whether the row existed.

    Which is why this page is `create` and not "insert". The primary key is chosen by the person
    filling the form —a warehouse and a SKU, both picked from a list— so "create a row that is
    already there" is not an error, it is a recount. The engine settles it with one `ON CONFLICT`
    instead of a read followed by a race.
    """
    warehouse_id, sku_id = _int_field("warehouse_id"), _int_field("sku_id")
    on_hand = _int_field("on_hand")
    if warehouse_id is None or sku_id is None or on_hand is None:
        flash("Pick a warehouse and a SKU, and give a whole number of units.", "error")
        return redirect(url_for("inventory.new_stock_form"))
    failure = usecases.count_stock(
        g.session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=on_hand
    )
    if failure is not None:
        flash("The on_hand cannot be negative.", "error")
        return redirect(url_for("inventory.new_stock_form"))
    flash("Stock counted.", "ok")
    return redirect(
        url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
    )


@inventory.get("/update/<int:warehouse_id>/<int:sku_id>")
def edit_stock_form(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """The edit form for an existing pair. 404 if the row went away since the link was made."""
    page = viewmodels.stock_form(g.session, warehouse_id, sku_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("inventory/update/inventory_update.html", **page)


@inventory.post("/update/<int:warehouse_id>/<int:sku_id>")
def update_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Correct the levels of an existing pair. The KEY comes from the URL, never from the form.

    That is not a shortcut: a composite key is not editable, because changing it does not edit this
    row — it means a different row entirely. The form disables the two selects and the URL carries
    the pair, so a posted `warehouse_id` cannot quietly move somebody's stock somewhere else.
    """
    on_hand, reserved = _int_field("on_hand"), _int_field("reserved")
    if on_hand is None or reserved is None:
        flash("Quantity and reserved both need a whole number.", "error")
        return redirect(
            url_for(
                "inventory.edit_stock_form", warehouse_id=warehouse_id, sku_id=sku_id
            )
        )
    result = usecases.update_stock(
        g.session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=on_hand,
        reserved=reserved,
    )
    if isinstance(result, Failure):
        if result.reason == "missing_fields":
            flash("Neither level can be negative.", "error")
            return redirect(
                url_for(
                    "inventory.edit_stock_form",
                    warehouse_id=warehouse_id,
                    sku_id=sku_id,
                )
            )
        return _render_failure(result)
    flash("Stock updated.", "ok")
    return redirect(
        url_for("inventory.stock_detail", warehouse_id=warehouse_id, sku_id=sku_id)
    )


@inventory.get("/delete/<int:warehouse_id>/<int:sku_id>")
def confirm_delete_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """The confirmation, and how much history a delete would take with it.

    A destructive action reached by a link needs a stop in between: a GET must not delete anything.
    And this stop earns its keep twice over here, because the movements' foreign key is RESTRICT —
    so the page can say the delete is impossible instead of offering a button that fails.
    """
    page = viewmodels.stock_delete_confirm(g.session, warehouse_id, sku_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template(
        "inventory/delete/inventory_delete.html",
        **page,
        conflict_message=_CONFLICT_MESSAGE,
    )


@inventory.post("/delete/<int:warehouse_id>/<int:sku_id>")
def delete_stock(warehouse_id: int, sku_id: int) -> ResponseReturnValue:
    """Delete a stock pair. 404 if it is gone, and a refusal in words if its history would be orphaned."""
    failure = usecases.remove_stock(g.session, warehouse_id=warehouse_id, sku_id=sku_id)
    if failure is not None:
        if failure.reason == "conflict":
            flash(_CONFLICT_MESSAGE, "error")
            return redirect(
                url_for(
                    "inventory.confirm_delete_stock",
                    warehouse_id=warehouse_id,
                    sku_id=sku_id,
                )
            )
        return _render_failure(failure)
    flash("Stock row deleted.", "ok")
    return redirect(url_for("inventory.list_stock"))


# ---- The two sheets the read-only view and the composite to-many needed -------------------------


@inventory.get("/alerts")
def stock_alerts() -> ResponseReturnValue:
    """What is running out, straight off the read-only VIEW. THREE statements, and no key anywhere.

    It takes nothing off the query string and there is no threshold to dial, which is the same
    decision the report makes about its own knobs and a stronger one here: "running out" is DEFINED
    by the view in the database, so this page and `/api/inventory/low-stock` cannot come to different
    conclusions about what to reorder. Moving the line is a migration.

    No `Failure` is possible. A stockroom with nothing running out is the answer everybody wants.
    """
    return render_template(
        "inventory/alerts/inventory_alerts.html",
        **viewmodels.low_stock_alerts(g.session),
    )


@inventory.get("/book")
def movement_book() -> ResponseReturnValue:
    """The movement book: the two origins that write the movements, in ONE ledger.

    THREE statements where the engine takes parentheses around a bounded branch and FOUR where it
    does not, and the page says which path it took rather than papering over it. No `Failure` is
    possible: a stockroom that has moved nothing is an answer.
    """
    return render_template(
        "inventory/book/inventory_book.html",
        **viewmodels.movement_book(g.session),
    )


@inventory.get("/warehouse/<int:warehouse_id>")
def warehouse_sheet(warehouse_id: int) -> ResponseReturnValue:
    """One warehouse, its stock and every movement of every line. FIVE statements, 404 if unknown.

    HALF a key, on purpose, and it is the only route in this module that takes one. Everywhere else
    half a pair identifies nothing; here the warehouse IS the row, and the stock hangs off it. The
    to-many underneath is the reason the page exists: the movements of every line arrive in a single
    select-in binding two placeholders per parent, which is the hardest relationship in the demos and
    had never been on a screen.
    """
    page = viewmodels.warehouse_sheet(g.session, warehouse_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("inventory/warehouse/inventory_warehouse.html", **page)


# ---- The two reading pages phase 4 added -------------------------------------------------------


@inventory.get("/report")
def stock_report() -> ResponseReturnValue:
    """The inventory report: FIVE statements, none of which grows with the number of rows.

    It takes no arguments off the query string, and that is deliberate rather than unfinished. The
    two knobs `stock_report` has —`minimum_moves` and `ranking_size`— change what the figures MEAN,
    and a report whose threshold can be dialled from a URL is a report where two people quoting the
    same page disagree about the number. The page prints the threshold it used instead; changing it
    is a code change, which is the honest cost of changing a definition.

    No `Failure` is possible: every figure is an aggregate, and an empty warehouse is an answer.
    """
    page = viewmodels.stock_report(g.session)
    return render_template("inventory/report/inventory_report.html", **page)


@inventory.get("/export")
def export_movements() -> ResponseReturnValue:
    """Every stock movement as a STREAMED CSV. One statement, and memory that does not grow.

    The generator is never touched here. `csv_response` writes the header and then pulls a row at a
    time from the cursor — and it TAKES THE SESSION WITH IT: `g.session` is popped, so the teardown
    hook has nothing to close and the stream owns the connection until the download ends. That is the
    last statement of this function for a reason; nothing may touch the session afterwards.
    `apps/exports.py` spells out why the documented `stream_with_context` is not what saves this, and
    it is the mistake that makes an export die on its first row rather than at the line that caused it.

    `?warehouse=` narrows the QUERY and not the writer. Filtering while writing would drag every
    movement of every warehouse out of the database in order to throw most of them away, on the one
    page whose entire subject is not doing that. An unknown id is still a filter the engine can run,
    so it downloads a file with a header and no rows — which is what "no movements" looks like.
    """
    export = viewmodels.stock_movements_export(
        g.session, warehouse_id=request.args.get("warehouse", default=None, type=int)
    )
    return csv_response(export)
