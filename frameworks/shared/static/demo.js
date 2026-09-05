// The demos' whole client. SHARED by Flask and Django, which both serve this file from
// `frameworks/shared/static/`. It is small on purpose: these pages are server-rendered, and every
// line here has to earn itself by improving something that already works without it.

// Navigation menus built out of a `<select>`. Choosing an option submits the form named by
// `data-form` (POST actions such as signing out) or navigates to its `value` (plain GET links). The
// first option is disabled and acts as the label.
function snakeNav(select) {
  const option = select.selectedOptions[0];
  if (option.dataset.form) {
    document.getElementById(option.dataset.form).submit();
  } else if (option.value) {
    location.href = option.value;
  }
}

// A control that cannot work without JavaScript stays hidden until JavaScript is here to work it.
// The alternative is a button that a reader with scripts off can press and that does nothing.
document.addEventListener("DOMContentLoaded", () => {
  for (const element of document.querySelectorAll("[data-needs-js]")) {
    element.hidden = false;
  }
});

// Re-reads the warehouse totals from the JSON API and repaints the table, without leaving the page.
// The server has already rendered those rows: this only replaces them with fresher ones, which is
// why the page loses nothing when this never runs.
//
// It is the JSON half of the ORM's debug report. A page turn on the lab's pager is HTML and carries
// its report in the `Server-Timing` and `X-Debug-Token` HEADERS; this is `application/json` and
// carries it in the BODY, under `snakeorm`, because the `envelope` channel is on. That is also why
// a list endpoint answers `{data, snakeorm}` rather than a bare array — hence the two shapes below.
async function snakeRefreshWarehouses(button) {
  const body = document.getElementById(button.dataset.target);
  const status = document.getElementById(button.dataset.status);
  button.disabled = true;
  try {
    const response = await fetch(button.dataset.endpoint, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const payload = await response.json();
    const rows = Array.isArray(payload) ? payload : payload.data;
    body.replaceChildren(...rows.map(snakeWarehouseRow));
    status.textContent = `${rows.length} warehouses, read at ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    status.textContent = `Could not refresh: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

// One row of the warehouse totals, built through the DOM and never through `innerHTML`: a warehouse
// name is something a reader typed into the catalogue form, and pasting it into markup is the demo
// teaching an injection.
function snakeWarehouseRow(stats) {
  const row = document.createElement("tr");
  row.append(
    snakeCell(stats.warehouse.code, "font-medium text-ink-900"),
    snakeCell(stats.warehouse.name, "text-ink-600"),
    snakeCell(stats.sku_count, "num"),
    snakeCell(stats.total_units, "num"),
  );
  return row;
}

function snakeCell(value, className) {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = value;
  return cell;
}
