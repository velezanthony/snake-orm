/// <reference path="./language.js" />
/// <reference path="./panel.js" />
/**
 * HISTORY module (`SnakeOrmHistory`) — the calls the page makes AFTER the render.
 *
 * The report above the panel is the one for the request that painted the page. Anything the page
 * fetches later never reloads it, so those queries are invisible to every other view. This module
 * stacks them, oldest first, in the tab the server left empty.
 *
 * It watches the TWO primitives a browser has — `fetch` and `XMLHttpRequest` — and no library's
 * events. HTMX goes through XHR and everything else through `fetch`, so the primitives cover
 * callers this file has never heard of; a list of libraries only ever finds the ones on the list.
 *
 * IT RUNS INSIDE SOMEBODY ELSE'S PAGE, and that is the rule every line below answers to. A throw
 * here breaks THEIR application, not this panel, so: the wrappers hand back exactly what the
 * original returned, they add no step to the app's own chain, everything of ours runs inside
 * `safe`, and nothing is patched at all when the tab cannot show what it collects.
 */
const SnakeOrmHistory = (() => {
  const safe = SnakeOrmPanel.safe;

  /** Class names (they match the CSS and `pages/history.html`). @enum {string} */
  const CLASS = {
    view: 'snk-view-history', list: 'snk-history-list', metrics: 'snk-hmetrics',
    entry: 'snk-h', head: 'snk-h-head', seq: 'snk-h-seq', path: 'snk-h-path',
    status: 'snk-h-status', count: 'snk-h-n', body: 'snk-h-body', note: 'snk-h-note',
    query: 'snk-h-q', sql: 'snk-h-sql', warn: 'snk-h-warn',
    tag: 'snk-tag', read: 'snk-select', write: 'snk-write', ms: 'snk-ms', n: 'snk-qn',
  };

  /**
   * i18n keys this module paints. They are all declared HERE because the panel's translation test
   * reads its list from this table: a key painted from somewhere else is a key nobody checks, and
   * the server-side scan cannot see anything the client writes. @enum {string}
   */
  const KEY = {
    queries: 'queries', empty: 'empty',
    warnings: 'hist_warnings', loading: 'hist_loading',
    gone: 'hist_gone', failed: 'hist_failed', none: 'hist_none',
  };

  /** `data-*` names (camelCase in `dataset`) and the value that switches the tab off. @enum {string} */
  const DATA = { envelope: 'envelope', key: 't' };
  const OFF = 'off';

  /** The sidecar's own prefix: its reports are asked for here, and never become entries themselves. */
  const SIDECAR = '/__snake__/';

  /** Per-XHR markers. Symbols so nothing of ours can collide with a property the app set. */
  const OPENED = Symbol('snakeorm-history-open');
  const WATCHED = Symbol('snakeorm-history-watched');

  // State (filled in by `mount`).
  /** @type {(key: string) => string} */ let translate = (key) => key;
  /** @type {(count: number, hot: boolean) => void} */ let onCount = () => {};
  /** @type {HTMLElement | null} */ let list = null;
  /** @type {HTMLElement | null} */ let metrics = null;
  /** @type {typeof fetch | null} */ let plainFetch = null;
  /**
   * Every call folded so far: the cards are arithmetic over THIS list and nothing else.
   * @type {{count: number | null, ms: number | null, mapping: number | null}[]}
   */
  const calls = [];
  let queries = 0;
  let hot = false;
  let seq = 0;

  // ===== Reading what the ORM said about a call ================================================

  /**
   * A `Server-Timing` header parsed into `{db: {dur, desc}, app: {...}, total: {...}}`.
   * Unknown metrics come through untouched: other middleware writes to this header too.
   */
  const timings = (header) => {
    const found = {};
    for (const part of String(header).split(',')) {
      const [name, ...rest] = part.split(';');
      if (!name.trim()) continue;
      const metric = {};
      for (const pair of rest) {
        const at = pair.indexOf('=');
        if (at > 0) metric[pair.slice(0, at).trim()] = pair.slice(at + 1).trim().replace(/^"|"$/g, '');
      }
      found[name.trim()] = metric;
    }
    return found;
  };

  /** How many queries a `db;desc="3 queries"` announces, or null when the header does not say. */
  const announced = (metric) => {
    const match = /^(\d+)\s/.exec((metric && metric.desc) || '');
    return match ? Number(match[1]) : null;
  };

  /** A number, or null when there is nothing to read. Absent is NOT zero and is not painted as one. */
  const number = (value) => (value === undefined || value === null || value === '' ? null : Number(value));

  /** The ORM's report inside an envelope body: the sibling key, on the object or on its `{data}` wrapper. */
  const reportIn = (payload) => (payload && typeof payload === 'object' ? payload.snakeorm || null : null);

  /** True when a report carries something the panel would light the badge for. */
  const burns = (report) => Boolean(report && report.warnings && report.warnings.length);

  /**
   * Folds one finished call into the entry it deserves, or null when the ORM said nothing about it.
   * An entry exists because a REPORT arrived — by header or by body. Without that rule the tab
   * would fill with every image, font and beacon the page happens to request.
   */
  const observed = (call) => {
    const header = call.header('Server-Timing');
    const report = call.report;
    if (!header && !report) return null;
    const timed = header ? timings(header) : {};
    const db = timed.db || null;
    const map = timed.map || null;
    return {
      method: call.method,
      path: call.path,
      status: call.status,
      count: report ? number(report.count) : announced(db),
      ms: report ? number(report.db_ms) : number(db && db.dur),
      mapping: report ? number(report.mapping_ms) : number(map && map.dur),
      token: call.header('X-Debug-Token'),
      report,
    };
  };

  // ===== The tab's own aggregate cards ==========================================================

  /**
   * NOT EVERY ENTRY BRINGS THE SAME DATA, and that is the whole design of this block. A JSON call
   * carries the full report in its body; an HTMX one carries only what fits in `Server-Timing`, and
   * with the `sidecar` channel off there is not even a token to ask for the detail. So a call can
   * arrive with no query count, or with no milliseconds.
   *
   * A call that did not report a number is NOT a zero. Summing the zeros gives a total that LOOKS
   * exact and is false, which is the one thing this panel exists not to do. Every aggregate carries
   * instead how much of the list it is computed over ("3/5"), and the card shows it.
   */
  const sum = (values) => values.reduce((total, value) => total + value, 0);
  const top = (values) => values.reduce((best, value) => (value > best ? value : best));

  /** Folds one field over the calls, DROPPING the ones that did not report it. */
  const fold = (field, reduce) => {
    const known = calls.map((call) => call[field]).filter((value) => value !== null);
    return {
      known: known.length,
      total: calls.length,
      value: known.length ? reduce(known) : null,
    };
  };

  /** Writes a value keeping the `<small>ms</small>` the server painted: only the number changes. */
  const setValue = (node, text) => {
    if (node && node.firstChild) node.firstChild.nodeValue = text;
  };

  const asInt = (value) => String(value);
  const asMs = (value) => value.toFixed(2);

  /** Paints one card: the number, and the coverage when it is not the whole list. */
  const paintCard = (name, folded, format) => {
    if (!metrics) return;
    const shown = folded.value === null ? '—' : format(folded.value);
    setValue(metrics.querySelector(`[data-hm="${name}"]`), shown);
    const part = metrics.querySelector(`[data-hm-part="${name}"]`);
    if (part) {
      part.textContent = folded.known < folded.total ? `${folded.known}/${folded.total}` : '';
    }
  };

  /** Recomputes every card from the list already in the client: no request, no new data. */
  const repaint = () => {
    const total = calls.length;
    paintCard('calls', { known: total, total, value: total }, asInt);
    paintCard('queries', fold('count', sum), asInt);
    paintCard('db', fold('ms', sum), asMs);
    paintCard('map', fold('mapping', sum), asMs);
    paintCard('slowest', fold('ms', top), asMs);
  };

  // ===== Painting ===============================================================================

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  /** A translated span that KEEPS its key, so switching language later reaches it like any other. */
  const label = (key) => {
    const node = el('span', null, translate(key));
    node.dataset[DATA.key] = key;
    return node;
  };

  /** A one-line note in the body of an entry (loading, gone, nothing to show). */
  const note = (key) => {
    const node = el('p', CLASS.note, translate(key));
    node.dataset[DATA.key] = key;
    return node;
  };

  /** Fills a body with a report: its warnings first, then one line per query. */
  const paintReport = (body, report) => {
    body.replaceChildren();
    const warnings = report.warnings || [];
    if (warnings.length) {
      const title = el('p', CLASS.warn);
      title.append(label(KEY.warnings));
      body.append(title);
      for (const warning of warnings) body.append(el('p', CLASS.warn, warning));
    }
    for (const query of report.queries || []) {
      const row = el('div', CLASS.query);
      row.append(
        el('span', CLASS.n, `#${query.n}`),
        el('code', CLASS.sql, query.sql),
        el('span', CLASS.ms, `${Number(query.ms).toFixed(2)} ms`),
      );
      body.append(row);
    }
    if (!body.childElementCount) body.append(note(KEY.empty));
  };

  /**
   * Asks the sidecar for the report of `token`, ONCE, the first time the entry is opened.
   * `404` is not a failure to hide: the ring buffer evicted it, and the entry says so.
   */
  const wireDetail = (details, body, token) => {
    let asked = false;
    details.addEventListener('toggle', () => {
      if (!details.open || asked) return;
      asked = true;
      body.replaceChildren(note(KEY.loading));
      // The ORIGINAL `fetch`: our own request is not one of the page's calls.
      plainFetch(`${SIDECAR}${token}`, {
        headers: { Accept: 'application/json' },
        credentials: 'same-origin',
      })
        .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
        .then((report) => {
          paintReport(body, report);
          if (burns(report)) bump(0, true);
        })
        .catch((status) => body.replaceChildren(note(status === 404 ? KEY.gone : KEY.failed)));
    });
  };

  /** One entry: a `<details>` (native, no state to keep) with the line, and the detail underneath. */
  const entry = (call) => {
    const item = document.createElement('li');
    const details = el('details', CLASS.entry);
    const head = el('summary', CLASS.head);
    head.append(
      el('span', CLASS.seq, `+${seq}`),
      el('span', `${CLASS.tag} ${call.method === 'GET' ? CLASS.read : CLASS.write}`, call.method),
      el('span', CLASS.path, call.path),
    );
    if (call.status) head.append(el('span', CLASS.status, call.status));
    if (call.count !== null) {
      const count = el('span', CLASS.count, `${call.count} `);
      count.append(label(KEY.queries));
      head.append(count);
    }
    if (call.ms !== null) head.append(el('span', CLASS.ms, `${call.ms.toFixed(2)} ms`));

    const body = el('div', CLASS.body);
    if (call.report) paintReport(body, call.report);
    else if (call.token && plainFetch) wireDetail(details, body, call.token);
    else body.append(note(KEY.none));

    details.append(head, body);
    item.append(details);
    return item;
  };

  /** Extends the badge: it counts the cost since the page loaded, so it only ever grows. */
  const bump = (count, burning) => {
    queries += count;
    hot = hot || burning;
    safe(() => onCount(queries, hot));
  };

  /** Puts one call at the TOP: the newest is what you opened the panel to see, so it needs no scroll. */
  const record = (call) => {
    const painted = observed(call);
    if (!painted) return;
    seq += 1;
    list.prepend(entry(painted));
    calls.push(painted);
    safe(repaint);
    bump(painted.count || 0, burns(painted.report));
  };

  // ===== Watching the two primitives ============================================================

  /** Calls this module has nothing to say about: another origin, or the sidecar answering us. */
  const ignored = (url) => url.origin !== location.origin || url.pathname.startsWith(SIDECAR);

  /** The verb of a `fetch(input, init)` call: the init wins, then a `Request`, then the default. */
  const verbOf = (args) => {
    const [input, init] = args;
    return String((init && init.method) || (input && input.method) || 'GET').toUpperCase();
  };

  /**
   * Wraps `fetch`. The caller gets the ORIGINAL promise back: no extra tick, no new object, no
   * chance of us changing the order anything settles in. We only branch off it to look.
   *
   * The empty rejection handler is what stops OUR branch from becoming an unhandled rejection of
   * its own on a failed request.
   */
  const watchFetch = () => {
    const original = window.fetch;
    if (typeof original !== 'function') return null;
    window.fetch = function (...args) {
      const promise = original.apply(this, args);
      safe(() => promise.then((response) => safe(() => fromFetch(response, args)), () => {}));
      return promise;
    };
    return original;
  };

  /** Reads a finished `fetch`, taking the JSON body off a CLONE so the app still gets its own. */
  const fromFetch = (response, args) => {
    const url = new URL(response.url || String(args[0]), location.href);
    if (ignored(url)) return;
    const header = (name) => response.headers.get(name);
    const call = {
      method: verbOf(args),
      path: url.pathname + url.search,
      status: response.status,
      header,
      report: null,
    };
    const type = header('Content-Type') || '';
    if (!type.includes('application/json') || response.bodyUsed) {
      record(call);
      return;
    }
    // `clone()` tees the stream instead of copying it, and this reader drains its half right away.
    const copy = response.clone();
    copy.json().then(
      (payload) => safe(() => record({ ...call, report: reportIn(payload) })),
      () => safe(() => record(call)),
    );
  };

  /**
   * Wraps `XMLHttpRequest`. `open` only notes the verb and the url (a `Response` carries neither),
   * and `send` adds ONE `load` listener — added, never assigned, so nothing of the app's is
   * displaced and its own handlers keep running first.
   */
  const watchXhr = () => {
    const proto = XMLHttpRequest.prototype;
    const open = proto.open;
    const send = proto.send;
    proto.open = function (...args) {
      safe(() => {
        this[OPENED] = { method: String(args[0] || 'GET').toUpperCase(), url: String(args[1] || '') };
      });
      return open.apply(this, args);
    };
    proto.send = function (...args) {
      safe(() => {
        if (this[WATCHED]) return;
        this[WATCHED] = true;
        this.addEventListener('load', () => safe(() => fromXhr(this)));
      });
      return send.apply(this, args);
    };
  };

  /** Reads a finished XHR. Free, unlike `fetch`: the body is already a string the app keeps. */
  const fromXhr = (xhr) => {
    const opened = xhr[OPENED] || {};
    const url = new URL(xhr.responseURL || opened.url || '', location.href);
    if (ignored(url)) return;
    const header = (name) => xhr.getResponseHeader(name);
    record({
      method: opened.method || 'GET',
      path: url.pathname + url.search,
      status: xhr.status,
      header,
      report: reportIn(safe(() => jsonOf(xhr, header('Content-Type') || ''))),
    });
  };

  /**
   * The parsed JSON body of an XHR, asked for the way its `responseType` allows: reading
   * `responseText` on a typed response throws, which is a throw inside somebody else's page.
   */
  const jsonOf = (xhr, type) => {
    if (!type.includes('application/json')) return null;
    if (xhr.responseType === 'json') return xhr.response;
    if (xhr.responseType === '' || xhr.responseType === 'text') return JSON.parse(xhr.responseText);
    return null;
  };

  // ===== Mounting ===============================================================================

  /**
   * Wires the tab and starts watching. It patches NOTHING and returns false when there is no list
   * to paint into or the `envelope` channel is off: the tab already explains itself in that case,
   * and patching a page's globals to collect what nobody can see is all cost and no feature.
   * @param {ShadowRoot | HTMLElement} root
   * @param {{translate: (key: string) => string, queries: number, onCount: (count: number, hot: boolean) => void}} wiring
   */
  const mount = (root, wiring) => {
    const view = root.querySelector(`.${CLASS.view}`);
    list = root.querySelector(`.${CLASS.list}`);
    metrics = root.querySelector(`.${CLASS.metrics}`);
    if (!view || !list || view.dataset[DATA.envelope] === OFF) return false;
    translate = wiring.translate;
    queries = wiring.queries || 0;
    onCount = wiring.onCount;
    plainFetch = watchFetch();
    watchXhr();
    return true;
  };

  return { CLASS, KEY, mount };
})();
