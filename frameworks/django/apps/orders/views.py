"""THIN SSR views of the orders domain: the taxonomy, the operation it was built for, and two more.

Eight routes. The five of the taxonomy, the operation page this whole domain exists to show, and the
report and export phase 4 gave every domain with data worth summarising. The last two are the only
ones in this module that touch no use case: a report is aggregates and an export is a CSV, and
neither of them writes anything.

Django is a dumb shell here, exactly as it is for the blog and for the pilot. A view parses the
request, calls ONE function of its own layer — a view model from `apps.orders.viewmodels` to read, a
use case from `apps.orders.usecases` to write — and turns the answer into a response. It never
touches a selector, never the session, and never builds a dict by walking a relation.

**These pages need NO login, and it is the same decision the pilot wrote down rather than a habit.**
An order HAS an owner, so unlike stock there would be something to compare a session against; what
there is not is anything to demonstrate by doing it. The blog's gate exists because hiding somebody
else's post behind a 404 is part of what the blog shows. Here the subject is a transaction that
declares its isolation, holds rows under a lock and rewinds to a savepoint, and putting a
registration in front of it would cost every reader of the demo a login to reach the one page these
demos exist for while testing nothing about the ORM.

**THE RULE THIS DOMAIN ADDS, and the one thing in this file that is not shaped like the pilot.**
`reserve`, `settle` and `cancel_order` open by DECLARING their isolation level, and
`SET TRANSACTION ISOLATION LEVEL` is only valid as the first statement of a transaction. Anything
that touches the database first spends that moment. So the three POST handlers below do NOT draw a
page, do NOT resolve the current user and do NOT load the order to name it in a message before they
call: they roll the request's session back and then call, and everything they need to say afterwards
they read afterwards.

What makes that worth six lines of prose is that breaking it is SILENT here. Postgres refuses the
statement only when it would CHANGE the level, and a stock Postgres already sits at the level the
operations ask for — so a handler that read first would pass every test on this machine, having
quietly stopped declaring its isolation and started inheriting the server's.
`default_transaction_isolation` is server-wide and MySQL, which these demos also run on, defaults to
`REPEATABLE READ`: there the loser of a race stops being told `conflict` and dies with a driver
serialisation error instead. `shared/viewmodels/orders_viewmodels.py` opens with the measurement and
`test_the_operation_is_handed_a_transaction_of_its_own` in this app's tests fails if the
`session.rollback()` calls below are deleted.

`not_found` from any use case becomes `layout/error.html` with a 404. The other reasons do not:
`conflict` and `payment_declined` re-render the page that offered the button, with the status they
map to, because a status code with no page behind it is a dead end for the person who pressed it.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST


from apps import exports
from apps.session import snake_session
from apps.blog.guards import current_user
from apps.orders import usecases, viewmodels
from apps.orders.models import OrderState
from apps.orders.usecases import Failure

# How many empty line slots the create form offers. Three because `place_order` wants at least one
# and the seeder's own orders carry one to three, so the form can express what the data already
# contains without any JavaScript. Growing an order past three is what the update page is for.
_CREATE_LINE_SLOTS = 3


_session = snake_session


def _not_found(request: HttpRequest) -> HttpResponse:
    """The 404 page, worded for this domain and pointing back at this domain's listing.

    The shell's error page takes its text from the context precisely so that a 404 in orders does not
    tell the reader that a stock pair is missing. One template, one layout, the words of whichever
    domain answered.
    """
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "error_message": "That order does not exist. It may have been deleted since the link was made.",
            "back_href": reverse("orders_list"),
            "back_label": "Back to orders",
        },
        status=404,
    )


def _customer_not_found(request: HttpRequest) -> HttpResponse:
    """The 404 of the customer sheet, which is about a PERSON and not about an order.

    `_not_found` above says an order may have been deleted since the link was made, and repeating
    that here would send somebody looking for a customer to check the order list. The sheet is
    reached from the report's customer table, so that is where it points back to.
    """
    return render(
        request,
        "layout/error.html",
        {
            "user": current_user(request),
            "error_message": "There is no customer with that id. Nobody with orders has ever been removed here, so the link is older than the database it is pointing at.",
            "back_href": reverse("orders_report"),
            "back_label": "Back to the report",
        },
        status=404,
    )


def _int_or_none(raw: str | None) -> int | None:
    """An integer out of a query-string or form value; `None` when it is absent or not a number.

    Everything that reaches here came from a URL or a form, which means it is a string somebody could
    have typed. `?page=abc` is a mistake, not a stack trace, and it is answered by falling back
    rather than by a 500 on a listing that has nothing wrong with it.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _posted_lines(request: HttpRequest) -> list[tuple[int, int]] | None:
    """The `(sku_id, quantity)` pairs a create form posted, or `None` if one of them is unreadable.

    The two lists arrive PARALLEL —`line_sku[i]` goes with `line_quantity[i]`— which is what a form
    of repeated rows gives you without any JavaScript, and `zip` is the whole of the pairing. A slot
    left empty is a slot the person did not fill in, so it is dropped; a slot with something
    unreadable in it is a different thing entirely and comes back as `None`, because silently
    dropping it would place an order missing a line the customer typed.
    """
    skus = request.POST.getlist("line_sku")
    quantities = request.POST.getlist("line_quantity")
    lines: list[tuple[int, int]] = []
    for raw_sku, raw_quantity in zip(skus, quantities, strict=False):
        if not raw_quantity.strip():
            continue
        sku_id, quantity = _int_or_none(raw_sku), _int_or_none(raw_quantity)
        if sku_id is None or quantity is None:
            return None
        lines.append((sku_id, quantity))
    return lines


def order_list(request: HttpRequest) -> HttpResponse:
    """The paginated listing, optionally narrowed to one state. TWO statements, whatever page.

    `parse_state` is imported and not re-derived: turning `?state=nonsense` into "no filter" rather
    than into a `ValueError` is a decision the view model already made, with its reasons written
    down, and a second `try/except` here would be that decision living in two places on two demos.
    """
    page = viewmodels.order_list(
        _session(request),
        state=viewmodels.parse_state(request.GET.get("state")),
        page=_int_or_none(request.GET.get("page")) or 1,
    )
    context: dict[str, object] = {
        **page,
        "user": current_user(request),
        "chooser": False,
    }
    return render(request, "orders/list/orders_list.html", context)


def order_operate_index(request: HttpRequest) -> HttpResponse:
    """The CHOOSER: the same listing, pinned to DRAFT, reached from the sidebar with no id.

    It exists because `shared/web/nav.py` puts `operate` in the sidebar and a sidebar link has
    nowhere to get an id. Pinning it to DRAFT is not a shortcut for "the first thing in the list": a
    draft is the state every one of the three operations is reachable from, so it is the only filter
    that guarantees the page it leads to has buttons on it.

    It renders the LIST template, with `chooser` saying which of the two it is. A sixth template that
    differed from `orders_list.html` by a heading and a link target is two pagers to keep in step.
    """
    page = viewmodels.order_list(
        _session(request),
        state=OrderState.DRAFT,
        page=_int_or_none(request.GET.get("page")) or 1,
    )
    context: dict[str, object] = {
        **page,
        "user": current_user(request),
        "chooser": True,
    }
    return render(request, "orders/list/orders_list.html", context)


def order_detail(request: HttpRequest, order_id: int) -> HttpResponse:
    """One order in full: its parties flattened, its lines, and its invoice if it reached one."""
    result = viewmodels.order_detail(_session(request), order_id)
    if isinstance(result, Failure):
        return _not_found(request)
    context: dict[str, object] = {**result, "user": current_user(request)}
    return render(request, "orders/detail/orders_detail.html", context)


def customer_sheet(request: HttpRequest, customer_id: int) -> HttpResponse:
    """One customer's whole order history, every line included. FIVE statements, 404 if unknown.

    The 404 is the half worth reaching from a page. `orders_of_customer` refuses an unknown customer
    instead of answering an empty list, and the difference matters exactly here: a person who has
    never ordered anything and a person who does not exist look identical on a page that cannot tell
    them apart, and only one of the two is a broken link.
    """
    page = viewmodels.customer_sheet(_session(request), customer_id)
    if isinstance(page, Failure):
        return _customer_not_found(request)
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "orders/customer/orders_customer.html", context)


def order_create(request: HttpRequest) -> HttpResponse:
    """GET: the empty form with its three pickers. POST: places the order and lands on it.

    The refusals are worded HERE and not read off the reason, because `place_order` answers
    `missing_fields` to four different mistakes — no reference, no lines, a quantity of zero, the
    same SKU twice — and "missing fields" is not something anybody can act on. The shape checks
    below name each one; what is left over is the reference already being taken, which is the only
    refusal another request can turn true while this one is being typed.
    """
    session = _session(request)
    user = current_user(request)
    form = viewmodels.order_form(session)
    if isinstance(
        form, Failure
    ):  # unreachable without an order id, and still not assumed away
        return _not_found(request)
    context: dict[str, object] = {
        **form,
        "user": user,
        "line_slots": range(_CREATE_LINE_SLOTS),
    }

    if request.method != "POST":
        return render(request, "orders/create/orders_create.html", context)

    reference = request.POST.get("reference", "").strip()
    customer_id = _int_or_none(request.POST.get("customer"))
    warehouse_id = _int_or_none(request.POST.get("warehouse"))
    lines = _posted_lines(request)
    if not reference or customer_id is None or warehouse_id is None:
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "An order needs a reference, a customer and a warehouse.",
            },
        )
    if lines is None:
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "A line has to say how many units, as a whole number.",
            },
        )
    if not lines:
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "An order with no lines is not an order. Fill in at least one.",
            },
        )
    if any(quantity <= 0 for _, quantity in lines):
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "A line of zero units is a line nobody asked for. Leave the slot empty instead.",
            },
        )
    if len({sku_id for sku_id, _ in lines}) != len(lines):
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "The same SKU is on two lines. Say it once, with the units you want.",
            },
        )

    placed = usecases.place_order(
        session,
        reference=reference,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=lines,
    )
    if isinstance(placed, Failure):
        if placed.reason == "conflict":
            return render(
                request,
                "orders/create/orders_create.html",
                {**context, "error": f"There is already an order called {reference}."},
                status=409,
            )
        # `not_found`: a customer, a warehouse or a SKU that has gone since the form was drawn. The
        # form is where that gets fixed, so it is re-rendered rather than answered with the 404 page.
        return render(
            request,
            "orders/create/orders_create.html",
            {
                **context,
                "error": "Something this order names is no longer there. Pick again.",
            },
            status=404,
        )
    return redirect("orders_detail", order_id=placed.id)


def order_update(request: HttpRequest, order_id: int) -> HttpResponse:
    """GET: the order with its lines editable. POST: ONE line edit, which is what the use cases are.

    There is no use case that changes an order's reference, customer or warehouse, and that is a
    decision of the domain rather than a gap: those three are what the lines were priced against and
    what the stock would be taken from, so moving them is placing a different order. The form shows
    them DISABLED, which is the same thing the pilot does with the two halves of its composite key
    and for the same reason — a disabled control posts nothing, so the only order this page can save
    is the one it was opened on, and the rule is the browser's rather than a check somebody has to
    remember to write.

    ONE edit per submit. `set_line` and `remove_line` each commit, so a bulk save would be several
    transactions wearing one button, and a failure halfway would leave the page showing an order that
    is neither what it was nor what was asked for. Which of the two ran is told by the FIELDS posted
    and not by the name of the button that was clicked: a button's name is sent only when it is the
    one pressed, which makes the branch depend on something no test can see.
    """
    session = _session(request)
    user = current_user(request)
    form = viewmodels.order_form(session, order_id)
    if isinstance(form, Failure):
        return _not_found(request)
    context: dict[str, object] = {**form, "user": user}

    if request.method != "POST":
        return render(request, "orders/update/orders_update.html", context)

    removed_sku = _int_or_none(request.POST.get("remove"))
    if removed_sku is not None:
        dropped = usecases.remove_line(session, order_id=order_id, sku_id=removed_sku)
        if isinstance(dropped, Failure):
            return _line_edit_failed(request, order_id, dropped)
        return redirect("orders_update", order_id=order_id)

    sku_id = _int_or_none(request.POST.get("sku"))
    quantity = _int_or_none(request.POST.get("quantity"))
    if sku_id is None or quantity is None:
        return render(
            request,
            "orders/update/orders_update.html",
            {**context, "error": "A line needs a SKU and a whole number of units."},
        )
    saved = usecases.set_line(
        session, order_id=order_id, sku_id=sku_id, quantity=quantity
    )
    if isinstance(saved, Failure):
        return _line_edit_failed(request, order_id, saved)
    return redirect("orders_update", order_id=order_id)


def _line_edit_failed(
    request: HttpRequest, order_id: int, failure: Failure
) -> HttpResponse:
    """The three ways a line edit is refused, each on the page that offered it.

    The form is rebuilt rather than reused because the edit may have half happened —`remove_line`
    commits— and a page redrawn from the context the request came in with would show the order as it
    was before, which is the one state it is certainly not in.
    """
    if failure.reason == "not_found":
        return _not_found(request)
    form = viewmodels.order_form(_session(request), order_id)
    if isinstance(form, Failure):
        return _not_found(request)
    message = (
        "A line of zero units is a removal, and removals have their own button."
        if failure.reason == "missing_fields"
        else (
            "This order has been billed. Its lines are what the invoice was calculated from, "
            "so they cannot move any more."
        )
    )
    return render(
        request,
        "orders/update/orders_update.html",
        {**form, "user": current_user(request), "error": message},
        status=400 if failure.reason == "missing_fields" else 409,
    )


def order_delete(request: HttpRequest, order_id: int) -> HttpResponse:
    """GET: the confirmation, which lists what would go. POST: the delete, or the refusal.

    The refusal is the interesting half and it is shown BEFORE the button is pressed: the foreign key
    from the lines is RESTRICT, so an order that has any cannot be deleted, and the confirmation
    renders the explanation — cancel it, do not delete it — instead of a button that fails. The POST
    path re-renders that same page with a 409 rather than inventing a second wording, because an
    order can gain a line between the page being drawn and the form being submitted.
    """
    session = _session(request)
    user = current_user(request)
    confirm = viewmodels.order_delete_confirm(session, order_id)
    if isinstance(confirm, Failure):
        return _not_found(request)

    if request.method != "POST":
        return render(
            request, "orders/delete/orders_delete.html", {**confirm, "user": user}
        )

    removed = usecases.remove_order(session, order_id=order_id)
    if isinstance(removed, Failure):
        if removed.reason == "not_found":
            return _not_found(request)
        return render(
            request,
            "orders/delete/orders_delete.html",
            {**confirm, "user": user},
            status=409,
        )
    return redirect("orders_list")


def order_operate(request: HttpRequest, order_id: int) -> HttpResponse:
    """The page the row lock, the isolation level and the savepoint are reached from. GET only.

    It is a read and nothing else, which is exactly why the three operations are routes of their own
    rather than a POST to this one: this page's six statements are what would spend the moment they
    need. See the module docstring.
    """
    return _operate_page(request, order_id)


def _operate_page(
    request: HttpRequest, order_id: int, *, error: str = "", status: int = 200
) -> HttpResponse:
    """The operation page, drawn from scratch, optionally carrying what just went wrong.

    Every caller reaches this AFTER its operation has finished, and the page is rebuilt from the
    database rather than from anything the handler was holding: `reserve` and `cancel_order` move the
    order and the stock, so the version of either that a handler read before calling would be a
    screenshot of a state that no longer exists.
    """
    page = viewmodels.order_operation(_session(request), order_id)
    if isinstance(page, Failure):
        return _not_found(request)
    context: dict[str, object] = {
        **page,
        "user": current_user(request),
        "error": error,
    }
    return render(request, "orders/operate/orders_operate.html", context, status=status)


@require_POST
def order_reserve(request: HttpRequest, order_id: int) -> HttpResponse:
    """POST: holds the order's units under a row lock, all of them or none.

    NOTHING ABOVE THE OPERATION MAY TOUCH THE DATABASE. The `rollback` is the fix the view models'
    module docstring prescribes and it is load-bearing, not tidying: it closes whatever transaction
    this request has already opened so that `reserve`'s `SET TRANSACTION ISOLATION LEVEL` is the
    first statement of a fresh one. Deleting it changes nothing on a stock Postgres — which is the
    whole danger — and turns the losing customer's `conflict` into a driver serialisation error on
    any server whose default is not `READ COMMITTED`, MySQL's included.
    """
    session = _session(request)
    session.rollback()
    reserved = usecases.reserve(session, order_id=order_id)
    if isinstance(reserved, Failure):
        if reserved.reason == "not_found":
            return _not_found(request)
        return _operate_page(
            request,
            order_id,
            error=(
                "The reservation was refused. Either the order is no longer a draft, or the "
                "warehouse does not have every line free — the lock read the real numbers."
            ),
            status=409,
        )
    return redirect("orders_operate", order_id=order_id)


@require_POST
def order_attach(request: HttpRequest, order_id: int) -> HttpResponse:
    """POST: bills an open order against an invoice that ALREADY exists. DRAFT or RESERVED -> INVOICED.

    The plain half of the joint with billing: it links the two rows and stops. `order_settle` below
    is the half that issues the invoice, takes the money and releases the hold if the payment does
    not land, which is why that one needs a savepoint and this one does not.

    NO `rollback` here, and that is not an omission: this operation takes no row locks and declares
    no isolation level, so it has nothing that needs to be the first statement of a fresh
    transaction. The other three say why they do.
    """
    session = _session(request)
    invoice_id = _int_or_none(request.POST.get("invoice"))
    if invoice_id is None:
        return _operate_page(
            request,
            order_id,
            error="Billing an order needs an invoice that already exists. Pick one.",
        )

    attached = usecases.attach_invoice(
        session, order_id=order_id, invoice_id=invoice_id
    )
    if isinstance(attached, Failure):
        if attached.reason == "not_found":
            return _not_found(request)
        return _operate_page(
            request,
            order_id,
            error=(
                "Billing was refused. Only an open order can be billed against an invoice, and "
                "this one has moved on."
            ),
            status=409,
        )
    return redirect("orders_operate", order_id=order_id)


@require_POST
def order_settle(request: HttpRequest, order_id: int) -> HttpResponse:
    """POST: bills the order against a subscription, takes the money and ships it.

    The subscription is read off the FORM, which is not a database read, so it happens before the
    `rollback` without costing the operation anything. Everything else this handler could want to
    know it asks for afterwards. See `order_reserve` for why the `rollback` is there.
    """
    session = _session(request)
    subscription_id = _int_or_none(request.POST.get("subscription"))
    if subscription_id is None:
        return _operate_page(
            request,
            order_id,
            error="Settling issues an invoice, and an invoice is issued against a subscription. Pick one.",
        )

    session.rollback()
    settled = usecases.settle(
        session, order_id=order_id, subscription_id=subscription_id
    )
    if isinstance(settled, Failure):
        if settled.reason == "not_found":
            return _not_found(request)
        if settled.reason == "payment_declined":
            return _operate_page(
                request,
                order_id,
                error=(
                    "The payment was declined. The invoice stands — it was issued before the "
                    "savepoint — and the units it had shipped are back on hold."
                ),
                status=402,
            )
        return _operate_page(
            request,
            order_id,
            error=(
                "The settlement was refused. Either the order is not reserved any more, or the "
                "subscription belongs to somebody else."
            ),
            status=409,
        )
    return redirect("orders_operate", order_id=order_id)


@require_POST
def order_cancel(request: HttpRequest, order_id: int) -> HttpResponse:
    """POST: cancels an open order, giving back whatever it was holding.

    A cancellation is a STATE and not a delete, so it lands back on the operation page rather than on
    the listing: the order is still there, and what changed is worth showing. See `order_reserve` for
    why the `rollback` is there.
    """
    session = _session(request)
    session.rollback()
    cancelled = usecases.cancel_order(session, order_id=order_id)
    if isinstance(cancelled, Failure):
        if cancelled.reason == "not_found":
            return _not_found(request)
        return _operate_page(
            request,
            order_id,
            error=(
                "This order cannot be cancelled. Once it has been billed, undoing it is a refund, "
                "which is a different operation with its own money in it."
            ),
            status=409,
        )
    return redirect("orders_operate", order_id=order_id)


def order_report(request: HttpRequest) -> HttpResponse:
    """The report: FIVE statements on Postgres and MySQL, SIX on SQLite, none of them growing.

    The engine is why the count is not a single number, and the page says which one it got: the
    highlights are ONE compound of two branches that each keep their own `LIMIT`, and a branch keeps
    a `LIMIT` only inside parentheses — which SQLite refuses. `union_supported` comes back on the
    context so the template can name the path that actually ran. A demo that hid that would be
    hiding the most interesting thing on the page.

    It cannot fail, and that is the view model's property rather than a branch missing here: every
    figure is an aggregate, so a shop with no orders yet is a page of zeroes instead of a 404.
    """
    page = viewmodels.order_report(_session(request))
    context: dict[str, object] = {**page, "user": current_user(request)}
    return render(request, "orders/report/orders_report.html", context)


def order_lines_export(request: HttpRequest) -> StreamingHttpResponse:
    """Every order line as a STREAMED CSV. ONE statement, and memory that does not grow.

    There is no template and there should not be one: an export is a file, not a page. What comes
    back is `text/csv` with a `Content-Disposition` naming the file, and the rows are written as the
    cursor yields them.

    THE SESSION IS NOT THE REQUEST'S, and `apps/exports.py` argues it in full. `SnakeSessionMiddleware`
    commits and closes `request.snake_session` the moment this function returns, and a streamed body
    is produced after that — so a generator reading from it would be reading from a session closed
    several frames ago. `csv_download` opens one that lives exactly as long as the download does,
    which is why this view hands it a FUNCTION rather than an export.

    `?state=` narrows the QUERY and not the writer, and `parse_state` is imported rather than
    re-derived for the reason the listing gives: turning `?state=nonsense` into "no filter" instead
    of into a `ValueError` is a decision the view model already made, with its reasons written down.
    """
    state = viewmodels.parse_state(request.GET.get("state"))
    return exports.csv_download(
        lambda session: viewmodels.order_lines_export(session, state=state)
    )
