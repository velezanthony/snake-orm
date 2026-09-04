"""SSR routes of the orders domain: the taxonomy's pages, plus the OPERATIONS this domain exists for.

Eight routes' worth of pages: the five of the CRUD taxonomy, the operations chooser, and the
`report`/`export` pair phase 4 gave every domain with data worth summarising. The last of those
renders no template on purpose — a CSV is a response, not a page.

The blueprint here is `orders` and there is no `orders-api` yet, which is the same convention the
rest of the demo follows — `blog`/`blog-api`, `inventory`/`inventory-api`: a plain name is the pages,
the `-api` suffix is the JSON. Naming it `orders` now is what leaves the plain name where it belongs
the day the JSON side arrives; the inventory domain had to take its name back from the API blueprint
for exactly this reason, and doing that once was enough.

**These pages need NO login, and that is a decision rather than an omission.** It is the same one the
inventory pages take, for the same reason: the blog gates its CRUD because a post belongs to
somebody and the ownership check is the thing being exercised. An order names a customer, but it is
not owned by whoever is looking at it — this demo is the warehouse's screen, not the customer's — so
a login step here would gate the pages without testing one thing about the ORM, and would put a
register-then-log-in preamble in front of every test of the row lock. The demo gates what has an
owner.

The views are THIN in the same sense as the inventory's: they parse the request, call the layer below
with FLAT parameters and translate the result. A GET calls `viewmodels`, a POST calls `usecases`.

**THE ONE RULE OF THIS MODULE THAT IS NOT STYLE: nothing may touch the database on the way into
`reserve`, `settle` or `cancel_order`.** Each of the three opens by DECLARING its isolation level, and
`SET TRANSACTION ISOLATION LEVEL` is only valid as the first statement of a transaction. Flask makes
that harder than it sounds, because `apps.blog.urls._open_session` is a `before_app_request` hook: it
runs on EVERY request of the whole app and resolves `g.current_user`, which is a query as soon as
anybody is signed in. By the time one of these three handlers is entered, the request's session can
therefore already be inside a transaction that has read something.

What that costs is worse than an exception, and it was measured rather than assumed — the module
docstring of `shared/viewmodels/orders_viewmodels.py` leads with it. Postgres refuses the statement
only when it would CHANGE the level, so on a stock server (whose default already IS `READ COMMITTED`)
the broken order of calls raises NOTHING: the operation quietly stops declaring its isolation and
starts inheriting it. `default_transaction_isolation` is a server-wide setting and MySQL — which these
demos also run on — defaults to `REPEATABLE READ`, the level under which the losing customer dies with
a driver serialisation error instead of being told `conflict`. Silent where it is written, fatal where
it is deployed.

The fix is one line, `g.session.rollback()`, immediately before each of the three calls, and it is
commented at each site so nobody deletes it as dead code on an otherwise clean request. A test pins
it: `test_the_operations_are_handed_a_session_with_no_transaction` in `verify.py` intercepts the use
case and asks the session for a level it does not already have, which is the one shape of the mistake
the engine is loud about.
"""

from __future__ import annotations

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

from apps.exports import csv_response
from apps.orders import usecases, viewmodels
from apps.orders.models import OrderState
from apps.orders.usecases import Failure

# The domain's PAGES. `-api` on the JSON one will keep the two apart in `url_for` when it lands.
orders = Blueprint("orders", __name__, url_prefix="/orders")

# A resource `Failure` to its HTTP code. Only `not_found` reaches here: `missing_fields` goes back to
# the form it came from with a message, and `conflict` is either the delete page's whole subject or a
# refusal the operations page already explains, so neither is an error page.
_STATUS_BY_REASON = {"not_found": 404}

# How many blank line slots the creation form offers. An order needs at least one line to be placeable
# —`place_order` refuses an empty one— and this demo has no JavaScript to grow the form, so the count
# is fixed and stated once instead of being spelled into the template's own loop.
_NEW_ORDER_LINES = 3

# What a refused operation says, keyed by the reason the use case gave. They are sentences and not a
# reason echoed at the user because `conflict` means something different for each of the three: a
# reservation loses a race for units, a settlement is billing an order in the wrong state, and a
# cancellation is being asked to undo money. The operations page states the same refusals BEFORE the
# button through `*_blocked`; these are for whoever arrived past it, from a stale tab or a curl.
_RESERVE_REFUSALS = {
    "conflict": (
        "The reservation was refused. Either the order is no longer a draft, or the warehouse "
        "does not have every line free — the stock is read again under a row lock, so what the "
        "page showed was the situation a moment earlier."
    ),
}
_SETTLE_REFUSALS = {
    "conflict": (
        "The settlement was refused: the order is not reserved, or the subscription belongs to "
        "somebody other than its customer."
    ),
    "payment_declined": (
        "The payment was declined. The invoice stands —a bill that was issued was issued— and the "
        "shipment was rewound to the savepoint, so the units are held again rather than gone."
    ),
}
_ATTACH_REFUSALS = {
    "conflict": (
        "Billing was refused: only an open order can be billed against an invoice, and this one has "
        "moved on."
    ),
}
_CANCEL_REFUSALS = {
    "conflict": (
        "The cancellation was refused: this order has been billed, and undoing that is a refund — "
        "a different operation, with its own money in it."
    ),
}


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

    `None` and not `0`: a form that posted no customer at all and a customer whose id is zero are
    different mistakes, and only the first one is a `<select>` that was never touched.
    """
    raw = request.form.get(name, "").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def _submitted_lines() -> list[tuple[int, int]]:
    """The `(sku_id, quantity)` pairs a creation form posted, dropping the slots left empty.

    The two lists are zipped rather than read by index because the browser posts them in document
    order and only names them once each — which also means a slot with a SKU and no quantity keeps
    its place instead of shifting every line below it onto the wrong number.

    Nothing is validated here beyond "both halves are numbers". A duplicated SKU, a quantity of zero
    and a SKU that does not exist are all refusals `place_order` already owns, and re-deciding them
    in the view is how the form and the use case end up disagreeing about what a valid order is.
    """
    pairs: list[tuple[int, int]] = []
    skus = request.form.getlist("line_sku_id")
    quantities = request.form.getlist("line_quantity")
    for raw_sku, raw_quantity in zip(skus, quantities, strict=False):
        if not raw_sku.strip():
            continue
        try:
            pairs.append((int(raw_sku), int(raw_quantity)))
        except ValueError:
            continue
    return pairs


# ---- The five pages ----------------------------------------------------------------------------


@orders.get("/list")
def list_orders() -> ResponseReturnValue:
    """The order listing: a real page of rows, a state filter and a pager. TWO statements.

    Two and not the inventory's three, because the filter's options are the `OrderState` enum and
    the code already knows them — there is no table of states to read. Neither statement depends on
    how many rows come back, which is what makes the page's cost flat.

    The filter goes through `viewmodels.parse_state`, which answers `None` to anything the enum
    refuses to build. That is deliberately NOT what the inventory does with an unknown warehouse id:
    an unknown id is still a filter the engine can run and correctly matches nothing, while an
    unknown state cannot be turned into a filter at all — so the alternatives are "show everything"
    or "raise at a hand-edited URL", and a typo in a query string is not a 500.
    """
    page = viewmodels.order_list(
        g.session,
        state=viewmodels.parse_state(request.args.get("state")),
        page=_int_arg("page", 1),
    )
    return render_template("orders/list/orders_list.html", **page)


@orders.get("/detail/<int:order_id>")
def order_detail(order_id: int) -> ResponseReturnValue:
    """One order in full: its three to-one hops already made, its lines and its invoice. 404 if absent."""
    page = viewmodels.order_detail(g.session, order_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("orders/detail/orders_detail.html", **page)


@orders.get("/customer/<int:customer_id>")
def customer_sheet(customer_id: int) -> ResponseReturnValue:
    """Everything one customer has ordered, with every line on every order. FIVE statements.

    The key is a CUSTOMER's and not an order's, which makes it the one route in this blueprint whose
    id names a row of another domain. The lines of every order arrive in ONE select-in rather than in
    one request per order, which is what the pages did before this page existed: the report named the
    customer and the reader had to open the orders one at a time to find out what was on them.

    404 and not an empty page for an unknown customer. Somebody who has never ordered anything and
    somebody who does not exist are the same empty list otherwise, and only one of the two is a link
    that is wrong.
    """
    page = viewmodels.customer_sheet(g.session, customer_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("orders/customer/orders_customer.html", **page)


@orders.get("/create")
def new_order_form() -> ResponseReturnValue:
    """The creation form: the three option lists and the blank line slots (`is_update` is false)."""
    page = viewmodels.order_form(g.session)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template(
        "orders/create/orders_create.html", **page, line_slots=_NEW_ORDER_LINES
    )


@orders.post("/create")
def create_order() -> ResponseReturnValue:
    """Place an order: the header, and at least one line, written as ONE unit of work.

    Every refusal comes back to the form rather than to an error page, `not_found` included, and
    that is the difference from the inventory's `create`. The customer, the warehouse and the SKUs
    were all picked from `<select>`s built moments earlier, so a `not_found` here does not mean "you
    asked for something that never existed" — it means the form went stale while it was open. The
    useful answer to that is the form again, freshly built, not a 404 about an order that was never
    created.
    """
    reference = request.form.get("reference", "").strip()
    customer_id, warehouse_id = _int_field("customer_id"), _int_field("warehouse_id")
    lines = _submitted_lines()
    if not reference or customer_id is None or warehouse_id is None or not lines:
        flash(
            "An order needs a reference, a customer, a warehouse and at least one line.",
            "error",
        )
        return redirect(url_for("orders.new_order_form"))

    result = usecases.place_order(
        g.session,
        reference=reference,
        customer_id=customer_id,
        warehouse_id=warehouse_id,
        lines=lines,
    )
    if isinstance(result, Failure):
        if result.reason == "conflict":
            flash(f"The reference {reference} is already taken.", "error")
        elif result.reason == "not_found":
            flash(
                "The customer, the warehouse or one of the SKUs is no longer there. "
                "The form has been rebuilt from what exists now.",
                "error",
            )
        else:
            flash(
                "Every line needs a whole number of units above zero, and a SKU cannot "
                "appear twice: two lines for one SKU say two different things about it.",
                "error",
            )
        return redirect(url_for("orders.new_order_form"))
    flash("Order placed.", "ok")
    return redirect(url_for("orders.order_detail", order_id=result.id))


@orders.get("/update/<int:order_id>")
def edit_order_form(order_id: int) -> ResponseReturnValue:
    """The edit page for an existing order. 404 if it went away since the link was made."""
    page = viewmodels.order_form(g.session, order_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template(
        "orders/update/orders_update.html", **page, line_slots=_NEW_ORDER_LINES
    )


@orders.post("/update/<int:order_id>")
def update_order(order_id: int) -> ResponseReturnValue:
    """Edit an order, which means editing its LINES: nothing else about it is editable.

    That is not a page half-written. The reference is what a customer quotes on the phone, the
    customer is who the order is for, and the warehouse is where its units are being held — and the
    domain offers no operation that changes any of the three, because none of them is an edit. A
    warehouse change on a reserved order is a release here and a hold there; a customer change is a
    different order. So the header is shown disabled and the lines are what this posts.

    The `action` field is what tells `set_line` from `remove_line`, and the two are NOT the same call
    with a quantity of zero. Zero is `missing_fields` in the use case on purpose: a form that submits
    an empty box would otherwise silently drop a line the customer never said to drop.

    `not_found` is the one refusal that becomes a 404 rather than a message, because unlike the
    creation form the id came from the URL — an order that is not there is the page itself being
    gone, not a `<select>` that went stale.
    """
    sku_id = _int_field("sku_id")
    if sku_id is None:
        flash("That line no longer names a SKU.", "error")
        return redirect(url_for("orders.edit_order_form", order_id=order_id))

    result: object | Failure
    if request.form.get("action", "") == "remove":
        result = usecases.remove_line(g.session, order_id=order_id, sku_id=sku_id)
        done = "Line removed."
    else:
        quantity = _int_field("quantity")
        if quantity is None:
            flash("A line needs a whole number of units.", "error")
            return redirect(url_for("orders.edit_order_form", order_id=order_id))
        result = usecases.set_line(
            g.session, order_id=order_id, sku_id=sku_id, quantity=quantity
        )
        done = "Line saved."

    if isinstance(result, Failure):
        if result.reason == "not_found":
            return _render_failure(result)
        if result.reason == "conflict":
            flash(
                "This order has been billed, so its lines are frozen: the invoice was "
                "calculated from them and changing them would leave it describing an order "
                "that no longer exists.",
                "error",
            )
        else:
            flash(
                "A line wants a whole number of units above zero. Removing a line is the "
                "Remove button, not a quantity of zero.",
                "error",
            )
        return redirect(url_for("orders.edit_order_form", order_id=order_id))
    flash(done, "ok")
    return redirect(url_for("orders.edit_order_form", order_id=order_id))


@orders.get("/delete/<int:order_id>")
def confirm_delete_order(order_id: int) -> ResponseReturnValue:
    """The confirmation, and what a delete would take with it.

    A destructive action reached by a link needs a stop in between: a GET must not delete anything.
    And this stop earns its keep twice over here, because the lines' foreign key is RESTRICT — so an
    order that has any cannot be deleted at all, and the page says so instead of offering a button
    that fails after being pressed.
    """
    page = viewmodels.order_delete_confirm(g.session, order_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("orders/delete/orders_delete.html", **page)


@orders.post("/delete/<int:order_id>")
def delete_order(order_id: int) -> ResponseReturnValue:
    """Delete an order. 404 if it is gone, and back to the confirmation if its lines would be orphaned.

    A refusal flashes NOTHING and returns to the confirmation page, which is the deliberate
    difference from the inventory's delete. There the view model emits no sentence, so the view holds
    the constant and says it in both places; here `order_delete_confirm` already builds `blocked`
    with the line count in it, and a second phrasing of the same complaint written into this module
    would be exactly the drift that constant exists to prevent — the same refusal explained two ways,
    with nothing to notice when they stop agreeing.
    """
    failure = usecases.remove_order(g.session, order_id=order_id)
    if failure is not None:
        if failure.reason == "conflict":
            return redirect(url_for("orders.confirm_delete_order", order_id=order_id))
        return _render_failure(failure)
    flash("Order deleted.", "ok")
    return redirect(url_for("orders.list_orders"))


# ---- The operations ----------------------------------------------------------------------------


@orders.get("/operate")
def choose_order() -> ResponseReturnValue:
    """The chooser: which order to operate on, narrowed to the drafts.

    It exists because the sidebar links this section with NO id — that contract is written into
    `shared/web/nav.py`, whose `orders` section carries `operate` as its one non-CRUD entry. An
    operation is something you go looking for rather than something you stumble into from a row, so
    the catalogue can name it; what it cannot do is invent a key for the link.

    Drafts, because a draft is where the flow starts and a chooser that listed every order would be
    the listing again under another name. The other states are reached the way they are actually
    reached — from the Operate control on a row of the listing, which every row carries.
    """
    page = viewmodels.order_list(
        g.session, state=OrderState.DRAFT, page=_int_arg("page", 1)
    )
    return render_template("orders/operate/orders_operate.html", order=None, **page)


@orders.get("/operate/<int:order_id>")
def operate_order(order_id: int) -> ResponseReturnValue:
    """The page the row lock, the isolation level and the savepoint are reached from. 404 if absent.

    SIX statements, none of which grows with the number of lines. It shows what the warehouse holds
    for every line and offers exactly the operations whose rules are met, printing the reason where
    they are not — the two never appear together, which is what `*_blocked` being empty exactly when
    its boolean is true buys the template.

    IT PERFORMS NOTHING, and it is not on the way to anything that does. The POSTs below are separate
    requests with a session each, for the reason the module docstring spends its second half on.
    """
    page = viewmodels.order_operation(g.session, order_id)
    if isinstance(page, Failure):
        return _render_failure(page)
    return render_template("orders/operate/orders_operate.html", **page)


def _finish(
    order_id: int, result: object | Failure, refusals: dict[str, str]
) -> ResponseReturnValue:
    """Turn an operation's answer into a response: 404 if the order is gone, else back to its page.

    Every refusal that is not `not_found` comes back to the operations page with its own sentence,
    because that page is where the same refusal is stated BEFORE the button — landing anywhere else
    would answer a click with a message and no way to see what it was about.
    """
    if isinstance(result, Failure):
        if result.reason == "not_found":
            return _render_failure(result)
        flash(refusals[result.reason], "error")
    return redirect(url_for("orders.operate_order", order_id=order_id))


@orders.post("/operate/<int:order_id>/reserve")
def reserve_order(order_id: int) -> ResponseReturnValue:
    """Hold every line's units under a ROW LOCK, all of them or none. DRAFT -> RESERVED.

    This is the operation the whole domain was built around: two customers wanting the same unit,
    settled by the engine rather than by luck.
    """
    # NOT dead code, and NOT a leftover. `reserve` declares its isolation level as the first
    # statement of its transaction, and the app-wide `before_app_request` hook has already spent this
    # session's transaction resolving `g.current_user` whenever somebody is signed in. Closing it
    # here is what leaves the operation a transaction of its own to declare. Deleting this line
    # raises nothing on a stock Postgres and breaks the demo on MySQL — see the module docstring.
    g.session.rollback()
    result = usecases.reserve(g.session, order_id=order_id)
    if not isinstance(result, Failure):
        flash("Reserved. The units are held for this order.", "ok")
    return _finish(order_id, result, _RESERVE_REFUSALS)


@orders.post("/operate/<int:order_id>/settle")
def settle_order(order_id: int) -> ResponseReturnValue:
    """Bill a reserved order against a subscription, take the money and ship it. RESERVED -> SETTLED.

    The subscription is posted from a `<select>` of the ORDER'S OWN customer's subscriptions, which
    is what the operations page builds it from: `settle` refuses one belonging to anybody else, and a
    free-text field here would be handing the user a refusal to click on.
    """
    subscription_id = _int_field("subscription_id")
    if subscription_id is None:
        # Reading the form is not reading the database, so this return is above the rollback without
        # costing the operation anything.
        flash("Pick the subscription this order is billed against.", "error")
        return redirect(url_for("orders.operate_order", order_id=order_id))
    # See `reserve_order`: the hook's transaction has to be closed before the operation declares its
    # isolation level. Same line, same reason, and it has to be here too — `settle` opens with the
    # same declaration.
    g.session.rollback()
    result = usecases.settle(
        g.session, order_id=order_id, subscription_id=subscription_id
    )
    if not isinstance(result, Failure):
        flash("Settled. The invoice is paid and the units have shipped.", "ok")
    return _finish(order_id, result, _SETTLE_REFUSALS)


@orders.post("/operate/<int:order_id>/cancel")
def cancel_order(order_id: int) -> ResponseReturnValue:
    """Cancel an open order, giving back whatever it was holding. DRAFT or RESERVED -> CANCELLED.

    A cancellation is a STATE and not a deletion: the order is history from the moment it exists, and
    a customer asking why theirs vanished is a question the database should be able to answer. Which
    is also why it takes the units back — from `RESERVED` the hold has to be released, or the shelf
    stays full while the warehouse starts refusing orders it could fill.
    """
    # See `reserve_order`: `cancel_order` declares its isolation level too, because releasing a hold
    # takes the same row locks that taking one does.
    g.session.rollback()
    result = usecases.cancel_order(g.session, order_id=order_id)
    if not isinstance(result, Failure):
        flash("Cancelled. Anything it was holding has gone back to the shelf.", "ok")
    return _finish(order_id, result, _CANCEL_REFUSALS)


@orders.post("/operate/<int:order_id>/attach")
def attach_invoice_to_order(order_id: int) -> ResponseReturnValue:
    """Bill an open order against an invoice that ALREADY exists. DRAFT or RESERVED -> INVOICED.

    The plain half of the joint with billing: it links the two rows and stops. `settle_order` above
    is the half that issues the invoice, takes the money and releases the hold if the payment does
    not land, which is why that one needs a savepoint and this one does not.

    No `rollback` here for the same reason: it takes no row locks and declares no isolation level, so
    it has nothing to be the first statement of.

    The invoice comes off the FORM and is looked up rather than trusted, so a stale id is a 404 from
    the use case instead of a foreign key violation raised inside the commit.
    """
    invoice_id = request.form.get("invoice_id", type=int)
    if invoice_id is None:
        flash(
            "Pick an invoice: billing an order needs one that already exists.", "error"
        )
        return redirect(url_for("orders.operate_order", order_id=order_id))
    result = usecases.attach_invoice(
        g.session, order_id=order_id, invoice_id=invoice_id
    )
    if not isinstance(result, Failure):
        flash("Billed. The order now points at that invoice.", "ok")
    return _finish(order_id, result, _ATTACH_REFUSALS)


# ---- The two reading pages -----------------------------------------------------------------------


@orders.get("/report")
def order_report() -> ResponseReturnValue:
    """The orders report: FIVE statements on Postgres and MySQL, SIX on SQLite.

    The engine is what decides, and the page says which path it took. `order_highlights` is a
    compound whose two branches each keep their own `LIMIT`, and a branch only keeps one inside
    parentheses — which SQLite refuses (`Cap.PARENTHESISED_COMPOUND` answers `Nope`), so there the
    view model runs the two branches separately and folds them in Python. `union_supported` travels
    onto the page for that reason and no other: it is the one figure here that depends on the engine
    instead of on the data, and a demo that hid it would be hiding the most interesting thing on it.

    Like the inventory's, it reads nothing off the query string. The three knobs `order_report` takes
    change what the numbers MEAN, and a threshold that can be dialled from a URL is a number two
    people can quote from the same page and disagree about. It prints the one it applied instead.
    """
    page = viewmodels.order_report(g.session)
    return render_template("orders/report/orders_report.html", **page)


@orders.get("/export")
def export_lines() -> ResponseReturnValue:
    """Every order line as a STREAMED CSV. One statement carrying THREE to-one hops.

    The order, its customer and its warehouse all ride in the same SELECT, which is the only reason
    an export can afford to print names instead of ids. Reading them off each line inside the writing
    loop would be a query per row, in a loop that is by definition long, in the one layer no
    `assert_queries` watches.

    `csv_response` takes the request's session with it, popping it off `g` so the teardown hook does
    not close a connection the stream has not finished with. It is the last statement here for that
    reason, and `apps/exports.py` carries the measurement behind it.

    `?state=` goes through `viewmodels.parse_state`, the same reading the listing uses, so an
    unrecognised state means NO filter rather than a stack trace on a hand-edited URL. The filter
    lands in the WHERE and not in the writer: narrowing while writing would pull every line of every
    state out of the database in order to drop most of them, on the one page whose whole subject is
    not pulling things out of the database.
    """
    export = viewmodels.order_lines_export(
        g.session, state=viewmodels.parse_state(request.args.get("state"))
    )
    return csv_response(export)
