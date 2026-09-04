/**
 * Debug panel — pure UI (`SnakeOrmPanel`). A catalogue of FUNCTIONS over the Shadow DOM; it knows
 * nothing about the language and never touches `window`. `mount` mounts and wires the intrinsic bits
 * (draggable FAB, per-card collapse, pager); the rest are operations the ORCHESTRATOR wires to the controls.
 */
const SnakeOrmPanel = (() => {
  /** Id of the (light DOM) container where `html.py` injects the panel; the orchestrator looks it up here. */
  const HOST_ID = 'snk-root';

  /** Class names (they match the CSS and `html.py`). @enum {string} */
  const CLASS = {
    root: 'snk', fab: 'snk-fab', panel: 'snk-panel', backdrop: 'snk-back',
    close: 'snk-close', theme: 'snk-theme',
    lang: 'snk-lang', menuItem: 'snk-menu-item', view: 'snk-view', active: 'snk-active',
    badge: 'snk-badge', hot: 'snk-hot',
    toggleAll: 'snk-all', pager: 'snk-pager', pageLabel: 'snk-pglabel', pageBtn: 'snk-pg', ps: 'snk-ps',
    query: 'snk-q', queryHead: 'snk-qh', light: 'snk-light', dragging: 'snk-drag',
    open: 'snk-open', show: 'snk-show', expanded: 'snk-exp', pagerActive: 'snk-on', hidden: 'snk-hidden',
  };

  /** The panel's own `sessionStorage` keys (the language is handled by its module). @enum {string} */
  const STORE = { position: 'snakeorm-debug-fab', theme: 'snakeorm-debug-theme' };

  /** `data-*` names (camelCase in `dataset`). `mounted` marks the host as already mounted. @enum {string} */
  const DATA = { pageSize: 'ps', direction: 'd', view: 'view', mounted: 'snkInit' };

  /** Pager directions (value of `data-d`). @enum {number} */
  const STEP = { prev: -1, next: 1 };

  /** Px threshold that tells a CLICK from a FAB drag. */
  const CLICK_SLOP = 6;
  /** Minimum margin from the FAB to the viewport edge, in px. */
  const EDGE = 8;

  // State (filled in by `mount`).
  /** @type {ShadowRoot | HTMLElement} */ let shadow;
  /** @type {HTMLElement} */ let wrap;
  /** @type {HTMLElement} */ let fab;
  /** @type {HTMLElement} */ let panel;
  /** @type {HTMLElement} */ let backdrop;
  /** @type {HTMLElement[]} */ let cards = [];
  let pageSize = 25;
  let pages = 1;
  let page = 0;
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let grabX = 0;
  let grabY = 0;

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /** Runs `fn` swallowing exceptions (sessionStorage fails in private mode). @template T */
  const safe = (fn) => {
    try {
      return fn();
    } catch {
      return null;
    }
  };

  const one = (cls) => shadow.querySelector(`.${cls}`);
  const many = (cls) => [...shadow.querySelectorAll(`.${cls}`)];
  const pageBtn = (dir) => shadow.querySelector(`.${CLASS.pageBtn}[data-${DATA.direction}="${dir}"]`);

  /** Places the FAB at (x, y), clamped to the viewport. */
  const place = (x, y) => {
    const { offsetWidth: w, offsetHeight: h } = fab;
    Object.assign(fab.style, {
      left: `${clamp(x, EDGE, innerWidth - w - EDGE)}px`,
      top: `${clamp(y, EDGE, innerHeight - h - EDGE)}px`,
      right: 'auto',
      bottom: 'auto',
    });
  };

  /** Opens/closes the offcanvas and hides the FAB when opening. */
  const setOpen = (show) => {
    panel.classList.toggle(CLASS.open, show);
    backdrop.classList.toggle(CLASS.show, show);
    fab.classList.toggle(CLASS.hidden, show);
    panel.setAttribute('aria-hidden', String(!show));
  };

  /** Shows only the current page's queries and updates the pager. */
  const paint = () => {
    cards.forEach((card, i) => {
      card.style.display = i >= page * pageSize && i < (page + 1) * pageSize ? '' : 'none';
    });
    const label = one(CLASS.pageLabel);
    if (label) label.textContent = `${page + 1} / ${pages}`;
    const prev = pageBtn(STEP.prev);
    const next = pageBtn(STEP.next);
    if (prev) prev.disabled = page === 0;
    if (next) next.disabled = page >= pages - 1;
  };

  /** Wires the draggable FAB (position persisted; small click = toggle). */
  const wireDrag = () => {
    const saved = safe(() => JSON.parse(sessionStorage.getItem(STORE.position)));
    if (saved) place(saved.x, saved.y);
    fab.addEventListener('pointerdown', (e) => {
      dragging = true;
      const r = fab.getBoundingClientRect();
      startX = e.clientX;
      startY = e.clientY;
      grabX = e.clientX - r.left;
      grabY = e.clientY - r.top;
      fab.setPointerCapture(e.pointerId);
      fab.classList.add(CLASS.dragging);
    });
    fab.addEventListener('pointermove', (e) => {
      if (dragging) place(e.clientX - grabX, e.clientY - grabY);
    });
    fab.addEventListener('pointerup', (e) => {
      if (!dragging) return;
      dragging = false;
      fab.classList.remove(CLASS.dragging);
      const r = fab.getBoundingClientRect();
      safe(() => sessionStorage.setItem(STORE.position, JSON.stringify({ x: r.left, y: r.top })));
      if (Math.hypot(e.clientX - startX, e.clientY - startY) < CLICK_SLOP) toggle();
    });
    addEventListener('resize', () => {
      const r = fab.getBoundingClientRect();
      place(r.left, r.top);
    });
  };

  /** Shows or hides the pager as needed (more than one page at the current size). */
  const updatePager = () => {
    const pager = one(CLASS.pager);
    if (pager) pager.classList.toggle(CLASS.pagerActive, pages > 1);
  };

  /** Changes how many queries show per page (0 = all), recomputes pages and repaints from the 1st. */
  const setPageSize = (n) => {
    pageSize = n > 0 ? n : Math.max(cards.length, 1);
    pages = Math.max(1, Math.ceil(cards.length / pageSize));
    page = 0;
    updatePager();
    paint();
  };

  /** Wires each card's own collapse and the pager (the buttons, ALWAYS). */
  const wireList = () => {
    cards.forEach((card) => {
      card
        .querySelector(`.${CLASS.queryHead}`)
        .addEventListener('click', () => card.classList.toggle(CLASS.expanded));
    });
    many(CLASS.pageBtn).forEach((btn) =>
      btn.addEventListener('click', () => {
        page = clamp(page + Number(btn.dataset[DATA.direction]), 0, pages - 1);
        paint();
      }),
    );
    updatePager();
    paint();
  };

  // ===== Operations it exposes (the orchestrator wires them to the controls) ====================

  /** What the FAB badge currently says, as a number (0 when there is no badge to read). */
  const badgeCount = () => Number(one(CLASS.badge)?.textContent) || 0;

  /**
   * Writes the FAB badge, and lights it amber when asked. It never puts the light OUT: the render
   * report may have turned it on for its own duplicates, and that fact does not stop being true
   * because a later call came back clean.
   */
  const badge = (count, hot) => {
    const element = one(CLASS.badge);
    if (!element) return;
    element.textContent = String(count);
    if (hot) element.classList.add(CLASS.hot);
  };

  const open = () => setOpen(true);
  const close = () => setOpen(false);
  const toggle = () => setOpen(!panel.classList.contains(CLASS.open));

  /** Toggles light/dark theme and persists it. */
  const theme = () => {
    const light = wrap.classList.toggle(CLASS.light);
    safe(() => sessionStorage.setItem(STORE.theme, light ? 'light' : 'dark'));
  };

  /** Button text key for the current state: 'expand' if any card is collapsed, otherwise 'collapse'. */
  const collapseKey = () =>
    cards.some((card) => !card.classList.contains(CLASS.expanded)) ? 'expand' : 'collapse';

  /** Expands or collapses ALL the cards. */
  const toggleAll = () => {
    const expand = collapseKey() === 'expand';
    cards.forEach((card) => card.classList.toggle(CLASS.expanded, expand));
  };

  /** Sets the "collapse all" button text for the current state, using the injected `translate`. */
  const syncCollapse = (translate) => {
    const button = one(CLASS.toggleAll);
    if (button) button.textContent = translate(collapseKey());
  };

  /** Activates the menu's `name` view (Queries/Help) and highlights its item. */
  const showView = (name) => {
    many(CLASS.menuItem).forEach((item) =>
      item.classList.toggle(CLASS.active, item.dataset[DATA.view] === name),
    );
    many(CLASS.view).forEach((view) =>
      view.classList.toggle(CLASS.active, view.classList.contains(`${CLASS.view}-${name}`)),
    );
  };

  /**
   * Mounts the panel on `host`: Shadow DOM + refs + wires the intrinsic bits (drag, cards, pager).
   * Returns the root the panel lives in (so the orchestrator can wire controls and language).
   * @param {HTMLElement} host @returns {ShadowRoot | HTMLElement}
   */
  const mount = (host) => {
    shadow = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
    shadow.appendChild(host.querySelector('template').content.cloneNode(true));
    pageSize = Number(host.dataset[DATA.pageSize]) || 25;
    wrap = one(CLASS.root);
    fab = one(CLASS.fab);
    panel = one(CLASS.panel);
    backdrop = one(CLASS.backdrop);
    cards = many(CLASS.query);
    pages = Math.max(1, Math.ceil(cards.length / pageSize));
    if (safe(() => sessionStorage.getItem(STORE.theme)) === 'light') wrap.classList.add(CLASS.light);
    wireDrag();
    wireList();
    return shadow;
  };

  // It also exposes its vocabularies (`HOST_ID`/`CLASS`/`DATA`) so the orchestrator wires without
  // literals, and `safe` so the other modules share ONE swallow-everything helper.
  return {
    HOST_ID, CLASS, DATA, safe, mount, open, close, toggle, theme,
    toggleAll, syncCollapse, showView, setPageSize, badge, badgeCount,
  };
})();
