/**
 * LANGUAGE module (`SnakeOrmLanguage`): the ES/EN TEXTS of everything rendered + the language
 * get/set. No i18n library: it holds the strings and swaps them. Self-contained (only it touches
 * its sessionStorage key); the orchestrator asks it for `t(key)` and sends it `apply`/`set`.
 */
const SnakeOrmLanguage = (() => {
  /** Valid languages (single source; exposed so the orchestrator never uses bare 'es'/'en'). @enum {string} */
  const LANG = { ES: 'es', EN: 'en' };
  /** Each language's name IN ITSELF (endonym), for the `<select>` options. @type {Record<string,string>} */
  const NAMES = { [LANG.ES]: 'Español', [LANG.EN]: 'English' };
  /** `sessionStorage` key for the language (only the user's CHOICE is stored, not the default). */
  const STORE_KEY = 'snakeorm-debug-lang';
  /** Language used when nothing is stored (public tool: English). */
  const DEFAULT = LANG.EN;

  /**
   * ES/EN texts. The server renders ES by default in the HTML marked with `data-t` (text),
   * `data-tt` (title) and `data-ta` (aria-label); `apply` replaces them. @type {Record<string, Record<string, string>>}
   */
  const STRINGS = {
    [LANG.ES]: {
      queries: 'queries', req: 'petición', db: 'en BD', map: 'mapeo', app: 'en app',
      dups: 'duplicadas', slowest: 'más lenta',
      queries_tip: 'Nº de sentencias SQL que corrió esta petición.',
      req_tip:
        'Tiempo total del request en el servidor, de principio a fin. No incluye el viaje de red ' +
        'hasta tu navegador.',
      db_tip:
        'Lo que la app esperó al driver, no lo que el motor tardó en ejecutar: incluye el viaje ' +
        'de red a la BD.',
      map_tip: 'Convertir filas en objetos: el coste del ORM. Tu código no está aquí dentro.',
      app_tip: 'El resto = petición − BD − mapeo: tu Python y la plantilla.',
      dups_tip: 'Misma SQL y misma línea corriendo más de una vez (posible N+1 o trabajo repetido).',
      slowest_tip: 'Duración de la query más lenta de esta petición.',
      collapse: 'Colapsar todo', expand: 'Expandir todo',
      per_page: 'Queries por página', per_page_all: 'Todas',
      empty: 'Sin queries', rows: 'filas devueltas/afectadas', origin_in: 'en',
      theme: 'Tema', theme_aria: 'Cambiar tema', close: 'Cerrar', lang: 'Idioma',
      prev: 'Anterior', next: 'Siguiente',
      warns_title: 'posibles N+1',
      warn_pre: 'La misma SQL corrió', warn_post: 'veces (posible N+1):',
      hint_title: 'Índices sugeridos', hint_suf: 'sin índice; una query lenta filtró aquí',
      menu_queries: 'Consultas', menu_history: 'Historial', menu_help: 'Ayuda',
      menu_config: 'Config', menu_cli: 'CLI', menu_dbfirst: 'DB-first',
      hcalls: 'llamadas',
      hcalls_tip: 'Llamadas que la página ha hecho desde que cargó.',
      hqueries_tip: 'Suma de las consultas de esas llamadas.',
      hdb_tip: 'Suma de lo que esas llamadas esperaron a la BD.',
      hmap_tip: 'Suma del mapeo de esas llamadas: filas convertidas en objetos.',
      hslowest_tip: 'La llamada que más esperó a la BD de toda la lista.',
      hpart_tip:
        'Calculado solo sobre las llamadas que trajeron el dato; las demás no cuentan como cero.',
      hist_title: 'Llamadas posteriores',
      hist_intro:
        'El informe de arriba es el de la petición que pintó esta página. Aquí se apilan las que ' +
        'vienen después, sin recargar.',
      hist_empty: 'Aún no hay llamadas.',
      hist_off: 'Falta el canal envelope',
      hist_off_d:
        'El histórico lee el informe que el ORM cuelga de las respuestas JSON. Sin ese canal no ' +
        'llega ninguno, así que aquí no habría nada que apilar:',
      hist_off_why:
        'El panel lo dice y no lo enciende: ssr y envelope son canales independientes y quien los ' +
        'elige eres tú.',
      hist_warnings: 'Avisos', hist_loading: 'Pidiendo el informe…',
      hist_gone: 'Ese informe ya no está: el buffer del sidecar solo guarda los más recientes.',
      hist_failed: 'No se pudo pedir el informe de esta llamada.',
      hist_none: 'Sin detalle: esta llamada solo trajo cabeceras. Enciende el canal sidecar.',
      badge_tip:
        'Consultas desde que cargó la página: las de esta petición más las de las llamadas ' +
        'posteriores, que verás en Historial.',
      help_enable: 'Activar el panel', help_json: 'JSON de la API',
      help_json_d: 'Con el canal envelope, en cada respuesta JSON bajo la clave', help_shortcuts: 'Atajos',
      help_shortcuts_d: 'Esc cierra · arrastra el botón para moverlo · ◐ tema · 🌐 idioma',
      help_read: 'Leer las consultas',
      help_read_d:
        '×N = misma consulta repetida · ↳ fichero:línea = de dónde salió · los ? ya llevan su valor ' +
        'real · pliega los avisos y elige cuántas queries ves por página para ganar sitio',
      cli_migrations: 'Migraciones', cli_make: 'crear migración', cli_migrate: 'aplicar',
      cli_rollback: 'deshacer la última', cli_status: 'aplicadas / pendientes',
      cli_fresh: 'recrear la BD desde cero', cli_squash: 'colapsar el histórico',
      cli_check: 'código contra la BD real', cli_generate: 'Generar',
      cli_scaffold: 'modelos desde una BD existente', cli_dto: 'TypedDicts desde tus modelos',
      cli_inspect: 'Inspección', cli_tables: 'listar tablas (--detail, --from-db)',
      cli_table: 'detalle de una tabla', cli_perf: 'Rendimiento',
      cli_advise: 'FKs sin índice (auditoría estática)',
      cfg_channels: 'Canales de debug',
      cfg_channels_d: 'Qué entrega el panel. Se combinan por coma:',
      cfg_ch_ssr: 'panel HTML inyectado en la respuesta',
      cfg_ch_envelope: 'el debug en el JSON, bajo la clave',
      cfg_ch_timing: 'cabecera Server-Timing',
      cfg_ch_sidecar: 'un token y su propia página en',
      cfg_ch_otel: 'DECLARADO y sin implementar: encenderlo no entrega nada y avisa',
      cfg_advise: 'Umbral del asesor',
      cfg_advise_d:
        'Solo sugiere índices para queries más lentas que X ms (por debajo, un índice no cambia nada):',
      cfg_advise_code: 'O tipado en código:', cfg_prod: 'Producción',
      cfg_prod_env:
        'Del entorno no se adivina nada: si hay un canal de riesgo encendido y nadie lo ha '
        + 'declarado —ni esta variable, ni production= en el middleware, ni SnakeDebugConfig— el '
        + 'arranque se niega en vez de elegir un defecto.',
      cfg_prod_d:
        'Los que entregan el SQL a quien pide —ssr, envelope y sidecar— se caen con production=True, aunque los configures. timing se queda: mide, no cuenta.',
      dbf_scaffold: 'Generar modelos', dbf_scaffold_d: 'Espeja una BD existente a modelos Python:',
      dbf_scaffold_u: 'Re-sincronizar (sobrescribe entero):', dbf_mirror: 'Modelo espejo',
      dbf_scaffold_out: 'Sin', dbf_scaffold_out2: 'no genera: no hay ruta por defecto y falla diciéndolo.',
      dbf_mirror_d:
        'marca un modelo como espejo: las migraciones lo IGNORAN. El esquema es del sysadmin, no nuestro.',
      dbf_mirror_adopt:
        'NO hay adopción in situ: cambiarlo a @snake_model no le entrega los mandos a las migraciones, porque el histórico no conoce la tabla y el autogen solo emitiría un CreateTable, que contra la tabla existente muere. Sirve para LLEVARSE el esquema a otra base gobernada desde cero.',
      dbf_names: 'Nombres de las clases',
      dbf_names_d: 'La clase se llama como la tabla, en CapWords y con el esquema delante:',
      dbf_names_u: 'deja los guiones bajos',
      dbf_names_s: 'quita el esquema; dos esquemas con la misma tabla COLISIONAN y se avisa',
      dbf_names_why:
        'No se quita el plural: eso es adivinar en inglés y rompe status, analysis o direcciones. Lo que no se puede nombrar se avisa y se deja fuera, nunca se inventa.',
      cfg_where: 'Qué va en config y qué en el comando',
      cfg_where_d: 'La regla: si la aplicación lo necesita para funcionar, va en config; si solo lo necesita esa invocación, va en flag.',
      cfg_where_cfg: 'databases, debug, advise_ms, migrations_dir, language',
      cfg_where_cli: 'Flags del comando:',
      cfg_where_db: '--database no sobrescribe nada: ELIGE una de las conexiones que declara la config. Un nombre que no esté no se puede crear desde el comando.',
      cfg_where_django: 'En Django no se declara aparte: el CLI sube hasta manage.py, lee su DJANGO_SETTINGS_MODULE y traduce settings.DATABASES + settings.SNAKEORM al mismo objeto.',
      dbf_check: 'Deriva',
      dbf_check_d: 'Compara el código con la BD real y avisa si no cuadran:',
    },
    [LANG.EN]: {
      queries: 'queries', req: 'request', db: 'in DB', map: 'mapping', app: 'in app',
      dups: 'duplicates', slowest: 'slowest',
      queries_tip: 'Number of SQL statements this request ran.',
      req_tip:
        'Total server-side request time, end to end. It does not include the network trip to ' +
        'your browser.',
      db_tip:
        'What the app WAITED on the driver, not what the engine took to run: the trip to the DB ' +
        'is in here.',
      map_tip: 'Turning rows into objects: the ORM cost. Your own code is not in here.',
      app_tip: 'The rest = request − DB − mapping: your Python and the template.',
      dups_tip: 'The same SQL from the same line, running more than once (possible N+1 or repeated work).',
      slowest_tip: 'Duration of the slowest query in this request.',
      collapse: 'Collapse all', expand: 'Expand all',
      per_page: 'Queries per page', per_page_all: 'All',
      empty: 'No queries', rows: 'rows returned/affected', origin_in: 'in',
      theme: 'Theme', theme_aria: 'Toggle theme', close: 'Close', lang: 'Language',
      prev: 'Previous', next: 'Next',
      warns_title: 'possible N+1',
      warn_pre: 'The same SQL ran', warn_post: 'times (possible N+1):',
      hint_title: 'Suggested indexes', hint_suf: 'no index; a slow query filtered here',
      menu_queries: 'Queries', menu_history: 'History', menu_help: 'Help',
      menu_config: 'Config', menu_cli: 'CLI', menu_dbfirst: 'DB-first',
      hcalls: 'calls',
      hcalls_tip: 'Calls the page has made since it loaded.',
      hqueries_tip: 'Sum of the queries of those calls.',
      hdb_tip: 'Sum of what those calls waited on the DB.',
      hmap_tip: 'Sum of the mapping of those calls: rows turned into objects.',
      hslowest_tip: 'The call that waited longest on the DB, of the whole list.',
      hpart_tip:
        'Computed only over the calls that reported the number; the rest do not count as zero.',
      hist_title: 'Calls after the render',
      hist_intro:
        'The report above is the one for the request that painted this page. The ones that come ' +
        'later, without a reload, stack up here.',
      hist_empty: 'No calls yet.',
      hist_off: 'The envelope channel is off',
      hist_off_d:
        'The history reads the report the ORM hangs off JSON responses. Without that channel none ' +
        'arrives, so there would be nothing to stack here:',
      hist_off_why:
        'The panel says so and does not switch it on: ssr and envelope are independent channels, ' +
        'and choosing them is yours.',
      hist_warnings: 'Warnings', hist_loading: 'Asking for the report…',
      hist_gone: 'That report is gone: the sidecar buffer only keeps the most recent ones.',
      hist_failed: 'The report for this call could not be fetched.',
      hist_none: 'No detail: this call only brought headers. Switch the sidecar channel on.',
      badge_tip:
        'Queries since the page loaded: this request plus the calls that came after it, which you ' +
        'can read in History.',
      help_enable: 'Enable the panel', help_json: 'API JSON',
      help_json_d: 'With the envelope channel, in every JSON response under the key', help_shortcuts: 'Shortcuts',
      help_shortcuts_d: 'Esc closes · drag the button to move it · ◐ theme · 🌐 language',
      help_read: 'Reading queries',
      help_read_d:
        '×N = same query repeated · ↳ file:line = where it came from · the ? already show their real ' +
        'value · fold the warnings and pick how many queries per page to gain room',
      cli_migrations: 'Migrations', cli_make: 'create migration', cli_migrate: 'apply',
      cli_rollback: 'undo last', cli_status: 'applied / pending',
      cli_fresh: 'rebuild the DB from scratch', cli_squash: 'squash history',
      cli_check: 'code against the real DB', cli_generate: 'Generate',
      cli_scaffold: 'models from an existing DB', cli_dto: 'TypedDicts from your models',
      cli_inspect: 'Inspection', cli_tables: 'list tables (--detail, --from-db)',
      cli_table: 'one table in detail', cli_perf: 'Performance',
      cli_advise: 'unindexed FKs (static audit)',
      cfg_channels: 'Debug channels',
      cfg_channels_d: 'What the panel delivers. They combine, comma-separated:',
      cfg_ch_ssr: 'HTML panel injected into the response',
      cfg_ch_envelope: 'the debug in the JSON, under the key',
      cfg_ch_timing: 'Server-Timing header',
      cfg_ch_sidecar: 'a token and its own page at',
      cfg_ch_otel: 'DECLARED and not implemented: switching it on delivers nothing and warns',
      cfg_advise: 'Advisor threshold',
      cfg_advise_d:
        'Only suggests indexes for queries slower than X ms (below that, an index changes nothing):',
      cfg_advise_code: 'Or typed in code:', cfg_prod: 'Production',
      cfg_prod_env:
        'Nothing about the environment is guessed: with a risky channel on and nobody having '
        + 'declared it —not this variable, not production= on the middleware, not '
        + 'SnakeDebugConfig— startup refuses rather than picking a default.',
      cfg_prod_d:
        'The ones that hand the SQL to the requester —ssr, envelope and sidecar— are dropped with production=True, even if configured. timing stays: it measures, it does not tell.',
      dbf_scaffold: 'Generate models', dbf_scaffold_d: 'Mirror an existing DB to Python models:',
      dbf_scaffold_u: 'Re-sync (overwrites entirely):', dbf_mirror: 'Mirror model',
      dbf_scaffold_out: 'Without', dbf_scaffold_out2: 'it generates nothing: there is no default path and it fails saying so.',
      dbf_mirror_d:
        'marks a model as a mirror: migrations IGNORE it. The schema belongs to the sysadmin, not to us.',
      dbf_mirror_adopt:
        'There is NO in-place adoption: switching it to @snake_model does not hand the controls to the migrations, because the history does not know the table and the autogen would only emit a CreateTable, which dies against the existing one. It is for TAKING the schema to another database governed from scratch.',
      dbf_names: 'Class names',
      dbf_names_d: 'The class is named after the table, CapWords, with the schema in front:',
      dbf_names_u: 'keeps the underscores',
      dbf_names_s: 'drops the schema; two schemas with the same table then COLLIDE, and it is reported',
      dbf_names_why:
        'The plural is left alone: removing it guesses at English and breaks status, analysis or direcciones. What cannot be named is reported and left out, never invented.',
      cfg_where: 'What goes in config and what in the command',
      cfg_where_d: 'The rule: if the application needs it to run, it goes in config; if only that invocation needs it, it is a flag.',
      cfg_where_cfg: 'databases, debug, advise_ms, migrations_dir, language',
      cfg_where_cli: 'Command flags:',
      cfg_where_db: '--database overrides nothing: it PICKS one of the connections the config declares. A name that is not there cannot be created from the command.',
      cfg_where_django: 'Django declares none of this twice: the CLI walks up to manage.py, reads its DJANGO_SETTINGS_MODULE and translates settings.DATABASES + settings.SNAKEORM into the same object.',
      dbf_check: 'Drift',
      dbf_check_d: 'Compares the code against the real DB and warns if they diverge:',
    },
  };

  /** Active language. @type {string} */
  let current = DEFAULT;

  const safe = (fn) => {
    try {
      return fn();
    } catch {
      return null;
    }
  };

  /** Active language. */
  const get = () => current;
  /** Translated text for `key` in the active language. */
  const t = (key) => STRINGS[current][key];
  /** The stored choice, or `null` if the user never chose. */
  const stored = () => safe(() => sessionStorage.getItem(STORE_KEY));

  /** Swaps texts (`data-t`), tooltips (`data-tt`) and aria (`data-ta`) in `root` to the active language. */
  const swap = (root) => {
    const dict = STRINGS[current];
    root.querySelectorAll('[data-t]').forEach((el) => {
      if (dict[el.dataset.t] != null) el.textContent = dict[el.dataset.t];
    });
    root.querySelectorAll('[data-tt]').forEach((el) => {
      if (dict[el.dataset.tt] != null) el.setAttribute('title', dict[el.dataset.tt]);
    });
    root.querySelectorAll('[data-ta]').forEach((el) => {
      if (dict[el.dataset.ta] != null) el.setAttribute('aria-label', dict[el.dataset.ta]);
    });
    // The <select> reflects the active language (its selected option).
    const select = root.querySelector('.snk-lang');
    if (select) select.value = current;
  };

  /** Applies a language to `root` WITHOUT persisting (for startup: it does not dirty the storage). */
  const apply = (root, lang) => {
    current = STRINGS[lang] ? lang : DEFAULT;
    swap(root);
    return current;
  };

  /** Changes the language and PERSISTS it (for the user's click). */
  const set = (root, lang) => {
    apply(root, lang);
    safe(() => sessionStorage.setItem(STORE_KEY, current));
    return current;
  };

  return { LANG, NAMES, DEFAULT, get, t, stored, apply, set };
})();
