"""THIN SSR views of the inventory domain: the taxonomy over a COMPOSITE key, plus report and export.

Nine pages and not five. `report` and `export` are the two phase 4 added to every domain with data
worth summarising, and each answers a different thing: the report is five aggregates that do not grow
with the data, and the export is not a page at all — it is a CSV, streamed, and it is the only route
in this module that does not render a template.

The last two answer questions this domain could not: `stock_alerts` reads the low-stock VIEW, which
until now was reachable from `/api/` and from nothing a person looks at, and `warehouse_sheet` puts
the to-many over the COMPOSITE key on a screen — a warehouse's whole stock with every movement of
every line, in one extra statement rather than one per pair.

Django is a dumb shell here, exactly as it is for the blog. A view parses the request, calls ONE
function of its own layer — a view model from `apps.inventory.viewmodels` to read, a use case from
`apps.inventory.usecases` to write — and turns the answer into a response. It never touches a
selector, never the session, and never builds a dict by walking a relation: `stock.warehouse.code` in
a view is the same N+1 as `stock.warehouse.code` in a template, moved one file up.

**These pages need NO login, and that is a decision rather than an omission.** Stock has no owner:
there is no `author_id` to compare a session against, so a login gate here would guard nothing and
would cost every reader of the demo a registration before they could see the page that exercises the
composite key. The blog gates its CRUD because the blog HAS ownership and hiding somebody else's post
behind a 404 is part of what it demonstrates; copying that gate to a domain with no owner would be
cargo cult, and it would test nothing about the ORM.

**Both halves of the key travel in the URL, always.** `/inventory/detail/3/7/` is one row and
`/inventory/detail/3/` is not half a row — it is a route that does not exist, which is the answer
this domain has to give. On the update form the two key selects arrive DISABLED for the same reason:
a composite key is not an editable field. Changing it does not move a row, it means a different row,
and a form that let you post a new pair into an update would silently create one while claiming to
edit another.

`not_found` from any use case becomes `layout/error.html` with a 404. `conflict` from the delete does
NOT: it re-renders the confirmation, which already explains in words why the pair cannot go, because
a status code with no page behind it is a dead end for the person who pressed the button.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST


from apps import exports
from apps.session import snake_session
from apps.blog.guards import current_user
from shared.models import SkuKind

from apps.inventory import usecases, viewmodels
from apps.inventory.usecases import Failure


_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing.

    The shell's error page takes its text from the context precisely so that a 404 in inventory does
    not tell the reader that a POST does not exist. One template, one layout, the words of whichever
    domain answered.
    """
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "error_message": "That stock row does not exist. Both halves of the key have to name a row that is there.",
            "back_href": reverse("inventory_list"),
            "back_label": "Back to stock",
        },
        status=404,
    )


def _warehouse_not_found(request: HttpRequest) -> HttpResponse:
    """The 404 of the warehouse sheet, which is about ONE half of the key and not about a pair.

    `_not_found` above talks about both halves, because every page it answers for is a stock row.
    This one is reached with a warehouse id alone, and telling somebody looking for a shed that
    "both halves of the key have to name a row" is an answer to a question they did not ask.
    """
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "error_message": "There is no warehouse with that id. It may have been opened on another database, or the link may be older than the catalogue.",
            "back_href": reverse("inventory_catalogue"),
            "back_label": "Back to the catalogue",
        },
        status=404,
    )


def _int_or_none(raw: str | None) -> int | None:
    """An integer out of a query-string or form value; `None` when it is absent or not a number.

    Everything that reaches here came from a URL or a form, which means it is a string somebody could
    have typed. `?warehouse=abc` is a mistake, not a stack trace, and it is answered by ignoring the
    filter rather than by a 500 on a listing that has nothing wrong with it.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def stock_list(request: HttpRequest) -> HttpResponse:
    """The paginated listing, optionally narrowed to one warehouse. THREE statements, whatever page.

    The page number and the filter both come off the query string and both go straight into the view
    model, which clamps them: `?page=999` is a stale bookmark and it lands on the last page rather
    than on an empty table with a pager that offers to go further.
    """
    page = viewmodels.stock_list(
        _session(request),
        warehouse_id=_int_or_none(request.GET.get("warehouse")),
        page=_int_or_none(request.GET.get("page")) or 1,
    )
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "inventory/list/inventory_list.html", context)


def stock_detail(request: HttpRequest, warehouse_id: int, sku_id: int) -> HttpResponse:
    """One pair in full: its two to-one relations flattened and its movements. 404 if it is not there."""
    return _detail_page(request, warehouse_id, sku_id)


def _detail_page(
    request: HttpRequest,
    warehouse_id: int,
    sku_id: int,
    *,
    error: str = "",
    status: int = 200,
) -> HttpResponse:
    """The detail page, rebuilt from the database, optionally carrying what just went wrong.

    Rebuilt and not reused: a movement changes the pair AND adds a row to its history, so a version
    read before the call would be a screenshot of a state that no longer exists.
    """
    result = viewmodels.stock_detail(_session(request), warehouse_id, sku_id)
    if isinstance(result, Failure):
        return _not_found(request)
    context: dict[str, object] = {
        **result,
        "user": current_user(request),
        "error": error,
    }
    return render(
        request, "inventory/detail/inventory_detail.html", context, status=status
    )


def _catalogue_page(
    request: HttpRequest, *, error: str = "", status: int = 200
) -> HttpResponse:
    """The catalogue, rebuilt from the database, optionally carrying what just went wrong."""
    page = viewmodels.inventory_catalogue(_session(request))
    context: dict[str, object] = {
        **page,
        "user": current_user(request),
        "error": error,
        "kinds": [kind.value for kind in SkuKind],
    }
    return render(
        request, "inventory/catalogue/inventory_catalogue.html", context, status=status
    )


def stock_catalogue(request: HttpRequest) -> HttpResponse:
    """What the inventory is made OF: the warehouses and the SKUs a stock pair points at.

    Every other page here is about what is IN the inventory. Until this one existed neither of the
    two things a pair points at could be made from a page, so the demo could only stock what the
    seeder had made.
    """
    return _catalogue_page(request)


@require_POST
def warehouse_create(request: HttpRequest) -> HttpResponse:
    """POST: a new warehouse. `code` is THREE characters, fixed, and the ORM refuses a fourth.

    The refusal is worth reaching from a page: the ORM shouts rather than truncating, so a code of
    four letters comes back as an error somebody can read instead of a row silently trimmed.
    """
    try:
        opened_on = date.fromisoformat(request.POST.get("opened_on", ""))
        shift_start = time.fromisoformat(request.POST.get("shift_start", ""))
        cutoff = time.fromisoformat(request.POST.get("cutoff", ""))
    except ValueError:
        return _catalogue_page(
            request,
            error="A warehouse needs an opening date, a shift start and a cutoff.",
        )
    code = request.POST.get("code", "")
    if len(code) > 3:
        return _catalogue_page(
            request,
            error=(
                "A warehouse code is three characters, fixed. The ORM refuses a fourth rather "
                "than trimming it in silence, which is why you are reading this instead of "
                "finding a shortened code later."
            ),
        )
    created = usecases.create_warehouse(
        _session(request),
        code=code,
        name=request.POST.get("name", ""),
        opened_on=opened_on,
        shift_start=shift_start,
        cutoff=cutoff,
    )
    if isinstance(created, Failure):
        return _catalogue_page(request, error="A warehouse needs a code and a name.")
    return redirect("inventory_catalogue")


@require_POST
def sku_create(request: HttpRequest) -> HttpResponse:
    """POST: a new SKU. The price is a `Decimal` and the lead time a `timedelta`, both from the form.

    Neither is a string by the time it reaches the use case, which is the layer's whole job: a price
    parsed as a float is the money bug this repository types its way out of.
    """
    try:
        price = Decimal(request.POST.get("price", ""))
        weight_kg = float(request.POST.get("weight_kg", ""))
        lead_time_days = int(request.POST.get("lead_time_days", ""))
        kind = SkuKind(request.POST.get("kind", ""))
    except (ArithmeticError, ValueError):
        return _catalogue_page(
            request,
            error="A SKU needs a price, a weight, a lead time in days and a kind.",
        )
    created = usecases.create_sku(
        _session(request),
        name=request.POST.get("name", ""),
        kind=kind,
        price=price,
        weight_kg=weight_kg,
        lead_time=timedelta(days=lead_time_days),
    )
    if isinstance(created, Failure):
        return _catalogue_page(
            request, error="A SKU needs a name and a price above zero."
        )
    return redirect("inventory_catalogue")


@require_POST
def warehouse_reserve(request: HttpRequest, warehouse_id: int) -> HttpResponse:
    """POST: holds units across the warehouse's WHOLE stock, in ONE statement.

    It is here and not on a pair's page because it is not about a pair: it is one UPDATE over every
    row of the warehouse, which is the operation this demo has to be able to show. The number of
    rows it touched comes back and the page says it.
    """
    units = _units_or_none(request.POST.get("units"))
    if units is None:
        return _catalogue_page(
            request, error="How many units per pair? It has to be a number above zero."
        )
    touched = usecases.reserve(
        _session(request), warehouse_id=warehouse_id, units=units
    )
    if isinstance(touched, Failure):
        return _not_found(request)
    return redirect("inventory_catalogue")


def _units_or_none(value: str | None) -> int | None:
    """A form field as a positive int, or `None` when it is missing, not a number, or not positive.

    Zero is refused here rather than passed on, and that is not the use case's rule being duplicated:
    a movement of nothing is not a refusal to explain, it is a form somebody submitted empty.
    """
    try:
        units = int(value) if value is not None else None
    except ValueError:
        return None
    return units if units is not None and units > 0 else None


@require_POST
def stock_receive(request: HttpRequest, warehouse_id: int, sku_id: int) -> HttpResponse:
    """POST: goods arrive into this pair. It creates the stock row if it was not there.

    It lives on the DETAIL page and not on one of its own, and that is the catalogue holding: a
    movement is something you do to the pair you are looking at, and its history is right there
    underneath. `orders` has an `operate` page because an operation there is something you go
    looking for; this is not that.
    """
    units = _units_or_none(request.POST.get("units"))
    if units is None:
        return _detail_page(
            request,
            warehouse_id,
            sku_id,
            error="How many units arrived? It has to be a number above zero.",
        )
    received = usecases.receive(
        _session(request), warehouse_id=warehouse_id, sku_id=sku_id, units=units
    )
    if isinstance(received, Failure):
        return _not_found(request)
    return redirect("inventory_detail", warehouse_id=warehouse_id, sku_id=sku_id)


@require_POST
def stock_ship(request: HttpRequest, warehouse_id: int, sku_id: int) -> HttpResponse:
    """POST: goods leave this pair. It refuses BEFORE writing when there are not that many.

    The refusal is the half worth having a page for: shipping more than there is comes back as a
    409 with the pair unchanged, rather than as a negative row the CHECK would have caught three
    layers down with a driver error.
    """
    units = _units_or_none(request.POST.get("units"))
    if units is None:
        return _detail_page(
            request,
            warehouse_id,
            sku_id,
            error="How many units left? It has to be a number above zero.",
        )
    shipped = usecases.ship(
        _session(request), warehouse_id=warehouse_id, sku_id=sku_id, units=units
    )
    if isinstance(shipped, Failure):
        if shipped.reason == "not_found":
            return _not_found(request)
        return _detail_page(
            request,
            warehouse_id,
            sku_id,
            error=(
                "There are not that many on the shelf. Nothing was written — the refusal happens "
                "before the movement, not after a negative row."
            ),
            status=409,
        )
    return redirect("inventory_detail", warehouse_id=warehouse_id, sku_id=sku_id)


def stock_create(request: HttpRequest) -> HttpResponse:
    """GET: the empty form. POST: the physical count, which is an UPSERT, then off to the row.

    `count_stock` does not care whether the pair existed — "this pair now holds N" is the same
    sentence either way — so the redirect goes to the detail of the pair that was just counted,
    whether that meant an INSERT or an UPDATE. Anything else would make the page lie about which of
    the two happened, and the person doing a stock count does not care.
    """
    session = _session(request)
    user = current_user(request)
    form = viewmodels.stock_form(session)
    if isinstance(
        form, Failure
    ):  # unreachable without a pair, and still not assumed away
        return _not_found(request)

    if request.method != "POST":
        return render(
            request,
            "inventory/create/inventory_create.html",
            {**form, "user": user},
        )

    warehouse_id = _int_or_none(request.POST.get("warehouse"))
    sku_id = _int_or_none(request.POST.get("sku"))
    on_hand = _int_or_none(request.POST.get("on_hand"))
    if warehouse_id is None or sku_id is None or on_hand is None:
        return render(
            request,
            "inventory/create/inventory_create.html",
            {
                **form,
                "user": user,
                "error": "A stock row needs a warehouse, a SKU and a on_hand.",
            },
        )

    result = usecases.count_stock(
        session, warehouse_id=warehouse_id, sku_id=sku_id, on_hand=on_hand
    )
    if isinstance(result, Failure):  # missing_fields: a negative count
        return render(
            request,
            "inventory/create/inventory_create.html",
            {**form, "user": user, "error": "The on_hand cannot be negative."},
        )
    return redirect("inventory_detail", warehouse_id=warehouse_id, sku_id=sku_id)


def stock_update(request: HttpRequest, warehouse_id: int, sku_id: int) -> HttpResponse:
    """GET: the form filled from the pair. POST: corrects its levels. 404 if the pair is gone.

    The pair comes from the URL and never from the form, because the form's two key selects are
    disabled and a disabled control posts nothing. That is not a workaround for the browser's rule —
    it IS the rule, used on purpose: the only pair this page can save is the one it was opened on.
    """
    session = _session(request)
    user = current_user(request)
    form = viewmodels.stock_form(session, warehouse_id, sku_id)
    if isinstance(form, Failure):
        return _not_found(request)

    if request.method != "POST":
        return render(
            request,
            "inventory/update/inventory_update.html",
            {**form, "user": user},
        )

    on_hand = _int_or_none(request.POST.get("on_hand"))
    reserved = _int_or_none(request.POST.get("reserved"))
    if on_hand is None or reserved is None:
        return render(
            request,
            "inventory/update/inventory_update.html",
            {
                **form,
                "user": user,
                "error": "Both levels are required: on_hand and reserved.",
            },
        )

    saved = usecases.update_stock(
        session,
        warehouse_id=warehouse_id,
        sku_id=sku_id,
        on_hand=on_hand,
        reserved=reserved,
    )
    if isinstance(saved, Failure):
        if saved.reason == "not_found":  # deleted between the form and the save
            return _not_found(request)
        return render(
            request,
            "inventory/update/inventory_update.html",
            {**form, "user": user, "error": "The levels cannot be negative."},
        )
    return redirect("inventory_detail", warehouse_id=warehouse_id, sku_id=sku_id)


def stock_delete(request: HttpRequest, warehouse_id: int, sku_id: int) -> HttpResponse:
    """GET: the confirmation, which says how much history would go. POST: the delete, or the refusal.

    The refusal is the interesting half and it is shown BEFORE the button is pressed: the foreign key
    from the movements is RESTRICT, so a pair with history cannot be deleted, and the confirmation
    renders the explanation instead of a button that fails. The POST path re-renders that same page
    with a 409 rather than inventing a second wording — a pair can gain a movement between the page
    being drawn and the form being submitted, and when it does, the answer has to read the same.
    """
    session = _session(request)
    user = current_user(request)
    confirm = viewmodels.stock_delete_confirm(session, warehouse_id, sku_id)
    if isinstance(confirm, Failure):
        return _not_found(request)

    if request.method != "POST":
        return render(
            request,
            "inventory/delete/inventory_delete.html",
            {**confirm, "user": user},
        )

    removed = usecases.remove_stock(session, warehouse_id=warehouse_id, sku_id=sku_id)
    if isinstance(removed, Failure):
        if removed.reason == "not_found":
            return _not_found(request)
        return render(
            request,
            "inventory/delete/inventory_delete.html",
            {**confirm, "user": user},
            status=409,
        )
    return redirect("inventory_list")


def stock_alerts(request: HttpRequest) -> HttpResponse:
    """What is running out, from the read-only VIEW. THREE statements, and no key in the URL.

    It cannot fail and it takes nothing off the query string, both for the same reason: the question
    is about the whole stockroom. There is no threshold to dial either — the rule of what "running
    out" means lives in the view in the database, so this page cannot disagree with the endpoint that
    reads the same view.
    """
    page = viewmodels.low_stock_alerts(_session(request))
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "inventory/alerts/inventory_alerts.html", context)


def movement_book(request: HttpRequest) -> HttpResponse:
    """The movement book: what the shop wrote and what the floor wrote, in one ledger.

    THREE statements where the engine takes parentheses around a bounded branch and FOUR where
    it does not, and the page says which it took. It cannot fail: a stockroom that has moved
    nothing is an answer.
    """
    page = viewmodels.movement_book(_session(request))
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "inventory/book/inventory_book.html", context)


def warehouse_sheet(request: HttpRequest, warehouse_id: int) -> HttpResponse:
    """One warehouse, its stock, and every movement of every line. FIVE statements, 404 if unknown.

    The interesting number is the one that is NOT here: there is no statement per line and none per
    movement. The whole history of the warehouse arrives in a single select-in over a foreign key two
    columns wide, which is the to-many this domain exists to demonstrate and the one no page showed
    until this one.
    """
    page = viewmodels.warehouse_sheet(_session(request), warehouse_id)
    if isinstance(page, Failure):
        return _warehouse_not_found(request)
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "inventory/warehouse/inventory_warehouse.html", context)


def stock_report(request: HttpRequest) -> HttpResponse:
    """The report: FIVE statements, and not one of them grows with the number of rows.

    It cannot fail, and that is a property of the view model rather than something decided here:
    every figure on the page is an aggregate, so an empty warehouse is an answer instead of a 404.

    The two knobs — how many moves make a SKU "busy", how deep the ranking goes — are left at their
    defaults instead of being read off the query string. A report whose thresholds anybody can retype
    is a page with a form on it, and the form is not what this page is demonstrating; the threshold
    still travels back in the context so the page can NAME the filter it applied, which is the part
    that makes a figure reproducible.
    """
    page = viewmodels.stock_report(_session(request))
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "inventory/report/inventory_report.html", context)


def stock_movements_export(request: HttpRequest) -> StreamingHttpResponse:
    """Every stock movement as a STREAMED CSV. ONE statement, and memory that does not grow.

    There is no template and there should not be one: an export is a file, not a page. What comes
    back is `text/csv` with a `Content-Disposition` naming the file, and the rows are written as the
    cursor yields them.

    THE SESSION IS NOT THE REQUEST'S, and `apps/exports.py` is where that is argued in full.
    `SnakeSessionMiddleware` commits and closes `request.snake_session` as soon as this function
    returns, and a streamed body is produced after that — so a generator reading from it would be
    reading from a session closed several frames ago. `csv_download` opens one that lives exactly as
    long as the download does, which is why this view hands it a FUNCTION rather than an export.

    `?warehouse=` narrows the QUERY and not the writer. Filtering while writing would pull every
    movement of every warehouse out of the database in order to throw most of them away, on the one
    page whose entire subject is not pulling things out of the database.
    """
    warehouse_id = _int_or_none(request.GET.get("warehouse"))
    return exports.csv_download(
        lambda session: viewmodels.stock_movements_export(
            session, warehouse_id=warehouse_id
        )
    )
