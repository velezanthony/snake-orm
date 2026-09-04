# Interioridades: dónde vive cada funcionalidad

`architecture.es.md` guarda las DECISIONES —el pipeline, las costuras, por qué la forma es la forma.
Esta página es la otra mitad: por cada funcionalidad que el roadmap sigue, **dónde está su código y
qué camino recorre un valor por dentro**. Está escrita para quien va a tocar una de ellas.

No es la guía de usuario, y es a propósito. Allí se ve cómo se LLAMA a una funcionalidad; aquí lo que
hace por dentro y qué fichero abrir.


## Consultas: un pipeline, dos emisores

Toda lectura recorre el mismo camino. `SnakeQuery` es INMUTABLE: cada método del builder devuelve
uno nuevo, así que un fragmento se puede guardar y reutilizar sin que nadie lo mute por detrás — que
es lo que permite que `shared/selectors/` sean funciones planas.

`to_sql` es la única puerta de salida y devuelve una tupla. Nada por debajo toca un driver.

```text
query/query.py     SnakeQuery.filter/order_by/limit/offset/distinct/group_by/having
                   -> a NEW SnakeQuery (frozen), never a mutation
query/query.py     .to_sql(dialect) -> (sql, params)      the ONLY door out
sql/select.py      emit_select(...)                        assembles the statement
sql/condition.py   emit_condition_into(...)                the WHERE, by isinstance chain
sql/value.py       emit_value(...)                         the values, by singledispatch
session/session.py _run(plan) -> driver.fetch_all(sql, params)
```

## Condiciones y valores: dos tuberías que no se portan igual

Esto es lo más útil que se puede saber antes de añadir un operador. Un nodo de VALOR se registra y
no se toca nada existente; un nodo de CONDICIÓN hay que añadirlo a una cadena cerrada en tres sitios,
y uno de ellos falla **en silencio**.

Que `expressions/paths.py` devuelva `[]` es lo que planifica los JOIN. Si se olvida la rama, la
consulta emite una columna sin cualificar y sin join detrás — y sin excepción por ninguna parte.

```text
VALUE  (SnakeValue[T])            open, additive
  sql/value.py      @emit_value.register(TheNode)   nothing else changes

CONDITION (SnakeCondition)         closed, three places
  sql/condition.py      isinstance branch   -> missing = SnakeNodeError   LOUD
  expressions/paths.py  isinstance branch   -> missing = return []        SILENT
  migration/render.py   isinstance branch   -> only for CHECK / partial index
```

## Relaciones: el grafo se construye una vez, al enlazar

El decorador compila cada clase por su cuenta y la registra suelta; `snake_link()` es lo que ata
los extremos, y HAY QUE LLAMARLO. Hasta entonces una relación sabe su propio nombre y nada de su
destino.

La navegación profunda (`A.b.c.d`) es la sobrecarga de acceso de CLASE de los descriptores, resuelta
contra ese grafo — sin codegen y sin plugin del type-checker.

```text
decorators/model.py   @snake_model  -> compile ONE class, register it loose
linker/              snake_link()   -> resolve every target, both directions
metadata/            SnakeRelationshipInfo(source_table, target_table, ...)
                     target_table follows the DECLARATION, not the foreign key
fields/relationship.py  class access -> type[M] / SnakeCollection[M]
                        instance access -> the loaded value, or it RAISES
sql/joins.py         include() -> LEFT JOIN (to-one) or a second select-in (to-many)
```

## Escrituras: un plan incoloro que ejecuta cualquiera de las dos sesiones

Toda escritura se decide en `session/planning.py`, que devuelve un `Plan` y no toca ningún driver.
Eso es lo que hace delgadas a las dos sesiones, y por lo que un fallo se arregla en un sitio y no en
dos.

`needs_rows` viaja en el plan en vez de adivinarse de la cadena: quien lo construyó sabe si hay un
`RETURNING` que leer.

```text
session/planning.py  plan_insert / plan_update / plan_delete / plan_upsert
                     -> Plan(sql, params, apply, needs_rows)
sql/insert.py        emits RETURNING where the engine has it
                     without it, the PK comes back via driver.last_insert_id (MySQL)
session/session.py   _run_plan(plan)          sync
session/asyncsession.py  await _run(plan)     same Plan, an await in front
```

## Tipos: dos registros que contestan dos preguntas distintas

Ir y volver son problemas distintos y tienen código distinto. `adapt_params` prepara un valor para
el DBAPI; `converter_for` reconstruye el tipo declarado a partir de lo que el driver devolvió.

El bug #39 vivía justo aquí: MySQL devuelve un `TIME` como `timedelta`, y hasta que el convertidor lo
supo, una columna declarada `time` volvía siendo otra cosa en un motor de tres.

```text
WRITE   sql/adapt.py     adapt_param(value, native_arrays=...)
                         native_arrays is answered by the DRIVER, not the dialect
READ    session/coercion.py  converter_for(python_type, scale)
                         resolved ONCE per column, never per row
                         None means 'passes through', and costs nothing
        the converter NEVER handles NULL: the caller guards it beforehand
```

## Consultas, una a una

### `filter()` y las condiciones

Cada llamada devuelve una consulta NUEVA, así que un fragmento se puede guardar sin miedo. El WHERE lo emite una cadena de `isinstance` que acaba en `SnakeNodeError` — un nodo que nadie le enseñó falla a gritos.

```text
query/query.py      filter(*conditions) -> new SnakeQuery
sql/condition.py    emit_condition_into(node, dialect, params, qualify, correlate)
expressions/paths.py  condition_paths(node)  -> which JOINs the WHERE needs
```

### `order_by` / `limit` / `offset`

La cláusula de paginación es del dialecto, porque los tres no la escriben igual y dos de ellos toman los valores como parámetros.

```text
query/query.py      order_by(*orders) / limit(n) / offset(n)
dialects/base.py    limit_offset(limit, offset, params) -> str
                    it appends to params: whether a slot can be a placeholder is the engine's answer
```

### `distinct`

Una bandera de la consulta que lee el emisor; no hay nodo aparte, porque `DISTINCT` es parte del SELECT y no una expresión.

```text
query/query.py      distinct() -> new SnakeQuery with the flag set
sql/select.py       emit_select writes SELECT DISTINCT
```

### `group_by` / `having`

`having` reutiliza el emisor de condiciones del WHERE: la gramática es la misma y solo cambia la posición. Un `group_by` sobre una relación profunda planifica su propio JOIN.

```text
query/query.py      group_by(*values) / having(*conditions)
sql/select.py       GROUP BY ... HAVING ...
sql/condition.py    the SAME emitter as the WHERE
```

### agregados (`count` `sum` `avg` `min` `max`)

Nodos de valor como cualquier otro: registran su handler y no cambian nada. Un `SUM` es nullable a propósito: sobre cero filas es NULL, y fingir lo contrario sería el ORM mintiendo sobre SQL.

```text
sql/aggregate.py    count() / sum_() / avg() / min_() / max_()
sql/value.py        @emit_value.register(...)  -> FUNC(expr)
```

### `string_agg`

De los pocos con tres NOMBRES distintos, así que es un hook de dialecto. El `order_by` viaja dentro de la llamada, y SQLite solo lo acepta desde 3.44 — medido, no supuesto.

```text
expressions/functions.py  string_agg(value, separator, order_by=...)
dialects/base.py    string_agg_sql(value, separator, order_by, params)
  postgres  string_agg(x, ?)        mysql  GROUP_CONCAT(x SEPARATOR ?)
  sqlite    group_concat(x, ? ORDER BY ...)
```

### `annotate()`

La fila base más escalares correlados, agrupando por la PK. Los nombres se validan al construir contra el `@snake_result` declarado, así que una errata falla antes de emitir SQL.

```text
session/session.py  annotate(query, ResultClass, **aggregates)
decorators/result.py  @snake_result declares the container
                    an extra or missing name -> SnakeEmitError, naming it
```

### `join()` explícito

Para la proyección que una relación no cubre. Entra en la misma lista de JOIN que llena `include()`, así que las dos no pueden duplicar.

```text
sql/joins.py        the JOIN list, shared with include()
query/query.py      join(target, on=...) -> new SnakeQuery
```

### `.any()` / `exists` correlado

Emite una subconsulta correlada, y `condition_paths` devuelve `[]` para ella A PROPÓSITO: sus columnas viven dentro de la subconsulta y no deben arrastrar JOIN a la de fuera.

```text
sql/condition.py    SnakeExists -> EXISTS (SELECT 1 FROM ... WHERE ...)
expressions/paths.py  returns [] for SnakeExists: no outer JOIN
```

### subconsulta escalar correlada

Un nodo de valor cuyo cuerpo es una consulta entera. Es lo que construye `annotate` por debajo, así que las dos comparten emisor en vez de criar cada una el suyo.

```text
expressions/scalar.py  the node
sql/value.py        emits (SELECT ... ) correlated to the outer row
```

### `IN` compuesto (`snake_keys`)

Una cadena de setters tipada que construye el `SnakeTupleIn` que ya existía. No añade `Cap` ni hook de dialecto — `Cap.ROW_CONSTRUCTOR` ya estaba y los tres contestan `Full()`.

```text
expressions/keys.py  snake_keys(M).in_([snake_key(M).set(col, val), ...])
sql/condition.py     SnakeTupleIn -> WHERE (a, b) IN ((?, ?), ...)
                     guarded against the engine's bind-parameter ceiling
```

### `only()` / `defer()`

La proyección estrecha el SELECT y la instancia RECUERDA lo que quedó fuera: tocarlo revienta en vez de contestar `None`, que sería indistinguible de un NULL de verdad.

```text
query/query.py      only(*columns) / defer(*columns)
fields/column.py    instance access to a deferred column -> SnakeColumnNotLoaded
```

### `iterate()` (cursor de servidor)

La costura de streaming, y vive en el Protocol del driver por un motivo: con solo `fetch_all`, una consulta de diez millones de filas construía la lista entera antes de devolver la primera.

```text
session/session.py  iterate(query, chunk=1000) -> Iterator[T]
drivers/base.py     fetch_iter(sql, params, chunk)
  postgres  a real server-side cursor    sqlite/mysql  fetchmany, bounding the peak
```

### `CASE` / `COALESCE` / `NULLIF`

Nodos de valor sin hook de dialecto: los tres motores los escriben igual, que conviene saberlo porque es raro.

```text
expressions/conditional.py  the nodes
sql/value.py        emitted as-is on the three engines
```

### funciones de ventana (`OVER`, frame)

El frame es parte del nodo y no una cadena pegada después, así que el orden de los parámetros sigue el textual — los marcadores se numeran por `len(params)`.

```text
expressions/window.py  row_number() / rank() / dense_rank() / lag() ... .over(...)
sql/value.py        FUNC(...) OVER (PARTITION BY ... ORDER BY ... frame)
```

### `UNION` / `INTERSECT` / `EXCEPT`

Un compuesto es un tipo propio con su propio `to_sql`, no una consulta con bandera. Parentizar ramas es capacidad declarada: SQLite no puede, y el plan se para en vez de emitir algo que va a rechazar.

```text
query/compound.py   SnakeCompound.to_sql(dialect)
dialects/capabilities.py  Cap.PARENTHESISED_COMPOUND
```

### `WITH RECURSIVE`

El ancla más el paso recursivo en una sentencia. `distinct=True` cambia `UNION ALL` por `UNION`, que es lo que hace que una caminata cíclica termine siquiera.

```text
query/recursive.py  .recursive(on=(child_col, parent_col), distinct=False)
                    reversing the pair walks the other way: ancestors, not descendants
dialects/capabilities.py  Cap.CTE_IN_COMPOUND_BRANCH
```

## Expresiones y funciones

### Funciones de texto

Un miembro de `SnakeFunc` por cada una, más una entrada por dialecto. El guardián del catálogo revienta al IMPORTAR si un dialecto se deja alguna, que es por lo que el silencio nunca significa «no soportada».

```text
expressions/scalar.py   SnakeFunc.LOWER / UPPER / TRIM / LENGTH / CONCAT / SUBSTRING / REPLACE
dialects/*.py           _<ENGINE>_FUNCTIONS maps each to its spelling
                        _<ENGINE>_CANNOT declares, with a reason, what it has not
                        set(SnakeFunc) - FUNCTIONS - CANNOT must be EMPTY at import
```

### Funciones de fecha

El caso más claro del catálogo de una afirmación que un test de cadena no puede hacer: el SQL es el mismo en todas partes y lo que cambia es quién lo va a ejecutar. SQLite declara que no puede ninguna de las dos.

```text
expressions/scalar.py   SnakeFunc.DATE_TRUNC / EXTRACT
dialects/sqlite.py      _SQLITE_CANNOT: both, with the reason written out
dialects/base.py        date_shift_sql(...)  for the arithmetic, which IS shared
```

### ABS y ROUND

Todos los builds de SQLite las traen, así que su ausencia de su tabla era un BUG (#34) y no un límite. Esa distinción es la razón entera de que `_CANNOT` exista al lado de `_FUNCTIONS`.

```text
expressions/scalar.py   snake_abs(value) / snake_round(value, digits=0)
dialects/*.py           present in all three _FUNCTIONS tables
note: ROUND(double, int) does not exist on Postgres; only the 1-arg form is asserted
```

### CEIL, FLOOR, SQRT y POWER

Traducidas por los tres y, a diferencia de `ABS`, una opción de COMPILACIÓN en SQLite. Eso no puede ser un `Cap` —una capacidad la contesta la clase del dialecto, que no sabe qué binario se enlazó—, así que el test le pregunta al binario ejecutando la consulta.

```text
expressions/scalar.py   snake_ceil / snake_floor / snake_sqrt / snake_power
dialects/sqlite.py      present, with the ENABLE_MATH_FUNCTIONS caveat in a comment
the probe is the query itself: 'no such function' -> skip, with the reason
```

### json_get()

Tres motores, tres MECANISMOS, y el `as_type` declarado es lo que importa: sin el cast la comparación va sobre TEXTO, donde '9' ordena por encima de '100'. La clave se interpola y nunca se parametriza, así que antes se valida contra un patrón de identificador estricto.

```text
expressions/expression.py  SnakeValue.json_get(*keys, as_type=...)  -> SnakeJsonGet
                        keys checked against ^[A-Za-z_][A-Za-z0-9_]*$ BEFORE emission
dialects/base.py        json_get_sql(source, key_path, as_type)
  postgres (x ->> 'k')::int   mysql CAST(JSON_UNQUOTE(JSON_EXTRACT(..)) AS SIGNED)
  sqlite   CAST(json_extract(x, '$.k') AS INTEGER)
```

### Operadores JSON de contención y ruta

NO implementados, y la forma que tendrían queda escrita aquí para que el siguiente intento no la redescubra. Son BOOLEANOS, así que caen en la cadena cerrada de condiciones — la del olvido de `paths.py` que pierde el JOIN en silencio.

```text
not implemented. If added:
  as a FUNCTION  -> a SnakeFunc member; test_function_catalogue covers it for free
  as an OPERATOR -> a node + dialect hook + FOUR isinstance branches
either way, the Degraded reason of Cap.JSON says 'cannot query INSIDE it' and would
have to be rewritten: the session shows it to the user at startup
```

### Operadores de array

NO implementados. Una columna `list[T]` ya va y vuelve en los tres —nativa en Postgres, texto JSON en los otros—, así que lo que falta es consultar DENTRO, que es justo lo que `Cap.ARRAYS` declara degradado en dos motores.

```text
sql/adapt.py        native_arrays is answered by the DRIVER, not the dialect
                    psycopg True   pymysql/sqlite3 False -> json.dumps
session/coercion.py  _to_list rebuilds the list from JSON text on the way back
dialects/capabilities.py  Cap.ARRAYS: Full on postgres, Degraded on the other two
```

### Búsqueda de texto completo

NO implementada, y el motivo es estructural y no de esfuerzo: SQLite necesita una TABLA VIRTUAL FTS5, o sea que no es una columna sino otro objeto de esquema. Un modelo escrito una vez dejaría de correr en los tres.

```text
not implemented. The three do not converge:
  postgres  tsvector + to_tsquery + a GIN index
  mysql     MATCH ... AGAINST + a FULLTEXT index
  sqlite    a separate FTS5 virtual table
the honest shape would be Full / Degraded / Nope in Cap, not a common denominator
```

### ILIKE

La capacidad más clara del catálogo: un motor tiene el operador, otro ya es insensible por collation y el tercero solo pliega ASCII. Correr la misma aserción en los tres sería incorrecto, no más estricto.

```text
sql/condition.py    reads supports_ilike before emitting
dialects/capabilities.py  syntax.has_ilike   -> WHICH SHAPE to write
                          Cap.ILIKE          -> HOW GOOD the result is
  postgres has_ilike=True  Full
  mysql    has_ilike=False Degraded (folds what the collation folds)
  sqlite   has_ilike=False Degraded (folds ASCII only)
```

### for_update() (bloqueo de fila)

Una cláusula que el emisor solo escribe donde el motor la tiene, leída del catálogo y no de una comprobación de versión.

```text
sql/select.py       reads supports_row_locking before appending the clause
dialects/capabilities.py  Cap.ROW_LOCKING
```

### raw()

La escotilla de escape, y lo que sigue garantizando es la HIDRATACIÓN: la forma `@snake_row` declarada vuelve tipada. La anchura se comprueba FILA A FILA, así que una consulta sin filas pasa aunque la forma esté mal.

```text
session/session.py  raw(sql, params, into=Row) -> list[Row]
session/planning.py plan_raw(into): positional hydration + per-row width check
                    a mismatch raises SnakeEmitError
the placeholder is the dialect's: ask dialect.placeholder(n), never hard-code $1/%s/?
```

## Escrituras

### insert / update / delete

Los tres se deciden en `planning.py`, que devuelve un `Plan` y no toca ningún driver. Por eso las dos sesiones son delgadas y por eso un fallo aquí se arregla una vez.

```text
session/planning.py  plan_insert / plan_update / plan_delete -> Plan(...)
sql/insert.py        the statement, parametrised; RETURNING where the engine has it
session/session.py   _run_plan(plan)      asyncsession.py  await _run(plan)
```

### escrituras masivas

Un INSERT multi-fila por lote, y el lote lo acota el techo de marcadores del motor, no un número que le gustara a alguien.

```text
session/session.py   add_all(instances)
dialects/capabilities.py  SnakeLimits.bind_params
  postgres/mysql 65535   sqlite 32766   -> the chunk size is derived, not chosen
```

### RETURNING

Donde el motor la tiene, la PK vuelve dentro del INSERT; donde no, la sesión le pregunta al driver por `last_insert_id`. Dos caminos, una capacidad declarada.

```text
dialects/capabilities.py  Cap.RETURNING   postgres/sqlite Full   mysql Nope
sql/insert.py        appends RETURNING only where supported
drivers/base.py      last_insert_id  is the OTHER path, and only MySQL walks it
```

### savepoint() / set_isolation()

El savepoint es un gestor de contexto que nombra su nivel (`sp1`, `sp2`), así que anidar reutiliza nombres de forma determinista. `set_isolation` REVIENTA donde el catálogo dice `Nope` en vez de emitir SQL que el motor va a rechazar.

```text
session/session.py  savepoint()  -> SAVEPOINT spN / RELEASE / ROLLBACK TO on error
                    the name is INTERNAL, never user data
                    set_isolation(level) -> SnakeUnsupportedFeature where Cap says Nope
dialects/capabilities.py  Cap.SET_ISOLATION
```

### with_retry

Reintenta solo lo que merece reintentarse: un conflicto de SERIALIZACIÓN, reconocido por el código del propio motor. Reintentar una violación de restricción sería repetirla.

```text
session/retry.py    with_retry(work, attempts=..., ...)
                    the retryable set is per engine, not a catch-all except
```

### Fallos de restricción

Una restricción violada, una excepción, en los tres. Se clasifica por el código que manda el motor —nunca por el mensaje, que es como un detector falla en abierto, y nunca por la CLASE del driver: en MySQL un `CHECK` llega como `OperationalError` y los otros tres como `IntegrityError`—. La excepción del driver va encadenada, así que la guardan `__cause__` y `driver_error`.

No se aplica a `fetch_iter`: es un generador, así que el envoltorio lo devolvería sin ejecutar nada — y recorre un SELECT, que no rompe ninguna restricción.

```text
drivers/failures.py   translate(error)  ->  the ORM exception, or None
                      @translating      ->  execute, fetch_all, commit
  postgres SQLSTATE   23505 23503 23502 23514
  mysql    errno      1062  1452  1048  4025/3819   (its SQLSTATE is 23000 for all four)
  sqlite   errorname  SQLITE_CONSTRAINT_UNIQUE / _FOREIGNKEY / _NOTNULL / _CHECK
never the message, and never the driver's exception class
```

### refresh()

Relee la fila SOBRE el objeto que ya se tiene, que es la única forma de ver lo que escribió un trigger o un valor por defecto. Un refresh de una fila que nadie más tocó no prueba nada.

```text
session/session.py  refresh(instance) -> re-reads by PK and writes the fields back
the demo exercises it where a TRIGGER keeps Post.visit_count
```

## Modelos y tipos

### Herencia polimórfica

Tabla única con columna discriminadora. El compilador anota qué subclase nombra cada valor, así que una consulta sobre la base hidrata la clase correcta sin una segunda lectura.

```text
decorators/model.py   the subclass declares its discriminator value
compiler/             one SnakeTableInfo, the subclass map inside it
session/planning.py   hydration picks the class from the discriminator column
```

### Vistas (@snake_view)

Una vista es un modelo cuyo cuerpo es una consulta, así que `view_body()` la renderiza en el dialecto DESTINO — una vista compuesta se escribe de nuevo por motor. `CREATE OR REPLACE` es capacidad declarada.

```text
decorators/view.py    @snake_view(query=...)
migration/ddl.py      emit_create_view -> view_body(dialect)
dialects/capabilities.py  Cap.REPLACE_VIEW -> where Nope, DROP + CREATE
```

### Señales y disparadores

Dos cosas distintas a propósito. Una SEÑAL es Python y se dispara alrededor de la sesión; un DISPARADOR es DDL y se cumple incluso para una escritura que no pasa por el ORM. Las escrituras masivas SE SALTAN las señales y lo avisan.

```text
core/signals.py       before_insert / after_update ... around the session
migration/operations.py  CreateTrigger / CreateFunction  -> real DDL
session/session.py    warn_bulk_skips_signals(...) on add_all / delete_where
dialects/capabilities.py  Cap.STORED_FUNCTIONS  Nope on mysql and sqlite
```

### Índices y restricciones

Se declaran en el modelo, se compilan al grafo, se emiten como DDL y el autodetector los diferencia. Un CHECK que compila y no valida nada es el fallo que este camino existe para evitar.

```text
fields/index.py       snake_index(...) / snake_unique(...)
decorators/check.py   snake_checks(Model, snake_check(cond, name=...))
                      declared OUTSIDE the class body: inside, the column has no name yet
migration/autodetect.py  indexes and constraints are diffed, not assumed
```

### Índices parciales

Un WHERE dentro del CREATE INDEX. MySQL no los tiene, y la degradación no es uniforme: un índice de BÚSQUEDA parcial se ensancha a la tabla entera (mismas filas, más espacio) mientras que uno UNIQUE parcial se RECHAZA, porque ensancharlo prohibiría duplicados que el dominio permite.

```text
fields/index.py       snake_index(..., where=...)
dialects/capabilities.py  Cap.PARTIAL_INDEXES
migration/ddl.py      widen a SEARCH index, refuse a UNIQUE one
```

### Métodos de índice (GIN / GIST / BRIN)

`USING <método>`, y el juego de métodos es del motor. MySQL tiene BTREE y HASH y no los de Postgres; SQLite tiene una sola clase y por tanto no admite método.

```text
fields/index.py       snake_index(..., method=...)
dialects/capabilities.py  Cap.INDEX_METHODS
  postgres Full   mysql Degraded (BTREE/HASH only)   sqlite Nope
```

### Comentarios (db_comment)

Comentarios de tabla y columna que viajan a la base de datos. MySQL no tiene `COMMENT ON`: un comentario es una CLÁUSULA, y cambiar el de una columna obliga a reescribirla entera con MODIFY COLUMN — así que se pierde lo que la base de datos tenga y el modelo no describa.

```text
fields/column.py      snake_column(db_comment=...)
dialects/capabilities.py  CommentStyle: COMMENT_ON / INLINE / UNSUPPORTED
  postgres COMMENT ON   mysql INLINE clause   sqlite UNSUPPORTED
```

### Convertidores de tipo (register_converter)

El camino de vuelta del usuario para un tipo de dominio. Se consulta ANTES del registro interno, así que una subclase de un tipo ya manejado puede declarar su propia conversión en vez de llegar como su base.

```text
core/converters.py    register_converter(type, to_db=..., from_db=...)
session/coercion.py   converter_for: user registry FIRST, then the internal one
                      mark_builtin(_CONVERTERS.keys()) stops a user rewriting a builtin
```

### Helpers UTC (SnakeUtc, utc_now, to_utc)

`SnakeUtc` es una subclase de `datetime` que no puede ser naive. Solo Postgres tiene un tipo que lleve zona, así que en los otros dos la garantía es del ORM entera — por eso el viaje de ida y vuelta se aserta en los tres.

```text
times.py             utc_now() / to_utc(v) / utc_from_zone(v, zone) / parse_utc(s)
                     SnakeUtc.of / .from_zone / .parse / .to_zone(zone)
session/coercion.py  _to_snake_utc closes the trip on the engines without a zone type
```

## Motores y drivers

### Aviso de salvedades al arrancar

La sesión avisa UNA vez por motor y por salvedad, y solo de las de tipo que un modelo declara de verdad — así que un proyecto sin columnas JSON nunca oye hablar de JSON.

```text
session/session.py  _warn_reduced_fidelity(dialect) from __init__, both sessions
                    _warned_caveats: module-level, so it is once per PROCESS
                    _relevant_caveats: all structural + type ones the models use
dialects/capabilities.py  caveats() -> (cap, reason) for everything not Full
```

### Drivers síncronos

Tres implementaciones de un Protocol. La dependencia pesada se importa DENTRO de `connect`, así que importar el driver no arrastra psycopg2 ni PyMySQL a un proyecto que no los usa.

```text
drivers/base.py     SnakeDriver: fetch_all / fetch_iter / execute / last_insert_id
                    commit / rollback / savepoint / release / rollback_to / close
drivers/psycopg.py  drivers/pymysql.py  drivers/sqlite.py
the connection object is never exposed: that is what lets one dialect serve every driver
```

### Drivers asíncronos

Postgres habla psycopg 3 nativo; los otros dos corren su driver SÍNCRONO en un hilo propio, que es lo que hace `aiosqlite` por dentro y da concurrencia real en MySQL porque el GIL se suelta mientras el socket espera.

```text
drivers/asyncbase.py     AsyncDriver: the SAME members, checked mechanically
drivers/asyncpsycopg.py  native
drivers/threaded.py      ThreadedAsyncDriver, max_workers=1 as a CORRECTNESS rule
drivers/asyncsqlite.py + asyncpymysql.py  subclass it, adding only connect()
```

### Pool de conexiones

El pool es agnóstico del motor: recibe tres invocables y solo la REGLA vive en él. El driver del pool va el más INTERNO, así que `close()` recorre la cadena de decoradores hacia abajo y llega a un cierre que DEVUELVE la conexión.

```text
drivers/pool.py     SnakePool(borrow, give_back, close_all, pre_ping=, recycle_seconds=, timeout_seconds=)
                    _PooledDriver.close() rolls back FIRST, then gives back
                    psycopg_pool(dsn, ...) is the only shipped factory, Postgres only
for the other two, write borrow/give_back/close_all: that is the intended surface
```

### Timeout de sentencia

Un mando de producción, no un adorno: una consulta colgada vacía un pool. Es una cadena del dialecto porque su sintaxis es de Postgres, y SQLite contesta `None` — así que `TimeoutDriver` se NIEGA a envolverlo en vez de devolver una conexión que aparenta estar acotada y no lo está.

```text
dialects/base.py    statement_timeout_sql(ms) -> str | None
  postgres SET statement_timeout = ms   mysql SET SESSION max_statement_time = s
  sqlite   None  (busy_timeout waits for a LOCK; it does nothing about a slow query)
drivers/timeout.py  None -> SnakeDialectError at construction, never a silent no-op
```

### Driver de logging

Un decorador que anota lo que pasa, a un escritor INYECTADO — así un test recoge en una lista y producción lo manda donde quiera. Anota también las fronteras, que es como se ve un COMMIT que falta.

```text
drivers/logging.py  LoggingDriver(inner, write=...)
                    COMMIT / ROLLBACK / CLOSE are logged, not only the SELECTs
order matters: put it INNERMOST of the decorators and it records what they do too
```

## Migraciones

### Diff y autodetección

Compara el grafo compilado contra el estado anterior, nunca contra la base de datos viva — una migración tiene que ser reproducible sin servidor. La deriva contra el esquema real es OTRA herramienta, a propósito.

```text
migration/autodetect.py  graph(previous) vs graph(now) -> [SnakeOperation]
                    columns, indexes, constraints and comments are all diffed
a NARROWING change (a shorter NUMERIC) is EMITTED and WARNED, not blocked:
the tool points, the human decides, and the engine is still the last net
```

### Runner (atómico por migración)

Una transacción por migración, no por operación: media migración aplicada es peor que ninguna. Donde el motor tiene DDL transaccional eso es real; donde no, el runner lo dice en vez de fingir.

```text
migration/runner.py      + asyncrunner.py, sharing the operation list
dialects/capabilities.py Cap.TRANSACTIONAL_DDL
migration/operations.py  SnakeOperation is runtime_checkable: the runner dispatches
                         by STRUCTURE (up_sql vs run/unrun), not by a registry
```

### RebuildTable (la salida de SQLite)

SQLite no puede quitar una columna que nombra una clave ajena y no tiene DROP CONSTRAINT para despejar, así que la tabla se reconstruye: crear la nueva, copiar, borrar, renombrar. Es decisión del USUARIO y va en una operación explícita, no a sus espaldas.

```text
migration/operations.py  RebuildTable(...)
                    the PRAGMA is a NO-OP inside a transaction: measured, not assumed
dialects/capabilities.py  Cap.DROP_COLUMN_CASCADES_FK
```

### RunPython (datos, con reverso)

Una migración de datos es código, así que declara su propia vuelta. El runner la reconoce por ESTRUCTURA —tiene `run`/`unrun` en vez de `up_sql`—, que es por lo que no hay registro que mantener al día.

```text
migration/operations.py  SnakeDataOperation: run(session) / unrun(session)
                    runtime_checkable, dispatched by shape
a RunPython without a reverse is a migration that cannot be rolled back, and says so
```

### Colapso (squash)

Muchas migraciones en una, dejando el ESTADO resultante idéntico. Lo que no puede colapsar es un `RunPython`: el código arbitrario no tiene álgebra, así que se arrastra en vez de fundirse.

```text
migration/squash.py  folds the operation list, preserving the final graph
a data operation survives the fold untouched
```

### Dependencias entre apps

Migraciones de varios paquetes ordenadas en una sola línea. El cargador construye un grafo y rechaza un ciclo en voz alta en vez de elegir un orden y confiar.

```text
migration/loader.py  reads each package, resolves `depends_on` into one order
                    a cycle raises, naming the migrations that close it
```

### Emisores DDL por motor (la matriz)

Cada emisor, por cada dialecto. La superficie se enumera DESDE EL CÓDIGO con `vars(ddl)`, así que un emisor nuevo sin entrada revienta la matriz — una matriz verde sobre una lista incompleta es el fallo del que protege.

```text
migration/ddl.py    emit_create_table / emit_add_column / emit_create_index / ...
the matrix skips per DECLARED capability, quoting it:
  'SQLite cannot: supports_schemas (`realize` stops it)'
and a CONTROL test asserts that what it says cannot run really cannot
```

## Database-first

### Introspección de PostgreSQL

Lee el catálogo vivo y construye el mismo grafo de metadata que construye el decorador, así que todo lo de aguas abajo —scaffold, drift, DDL— funciona sobre él sin saber de dónde salió.

```text
introspection/postgres.py  reads information_schema + pg_catalog
                    -> SnakeTableInfo / SnakeColumnInfo / ...  the SAME shapes
introspection/base.py  SnakeIntrospector Protocol
```

### Introspección de MySQL

El mismo Protocol sobre otro catálogo, y las diferencias no son cosméticas: MySQL confunde un comentario vacío con ninguno, así que lo que vuelve es lo que el modelo puede describir y nada más.

```text
introspection/mysql.py   information_schema, MySQL's own columns
an empty comment and no comment are the same value here: it cannot be round-tripped
```

### Introspección de SQLite

PRAGMAs en vez de catálogo, y el tipo es el que DECLARÓ la columna — SQLite guarda afinidad, así que un scaffold lee la declaración, no los valores.

```text
introspection/sqlite.py  PRAGMA table_info / index_list / foreign_key_list
the declared type is the source: affinity means the values do not tell you the type
```

### Scaffold de modelos

Convierte un grafo introspectado en código Python. Renderiza los alias genéricos RECURSIVAMENTE y registra los imports que esa recursión necesita; lo que no puede renderizar lo RECHAZA en voz alta en vez de degradarlo.

```text
introspection/scaffold.py  graph -> source text
                    render_type recurses, and the recursion is what registers imports
                    what cannot be rendered raises; it does not fall back to a guess
```

### Detección de deriva

Compara el código contra la base de datos VIVA, que es la pregunta contraria a la del autodetector. Solo mira lo que el código DECLARA: las tablas de otra aplicación en la misma base no generan ruido.

```text
introspection/drift.py   declared graph vs current_schema()
                    include_unmanaged=True brings in the @snake_db_first mirrors
                    it compares storage_type, not python_type
```

## Debug

### Colector y DebugReport

El driver de captura escribe en un ámbito guardado en un `ContextVar`, así que no hay que enhebrar nada por la cadena de llamadas — y sin ámbito abierto delega directo a coste cero. El origen se resuelve DENTRO de `add`, mientras la pila del llamante sigue viva.

```text
debug/capture.py     CaptureDriver(inner, system=...)  installed via config.open(wrap=...)
debug/collector.py   capture_queries() opens the scope; current_collector() reads it
                     no scope -> delegate, no cost
debug/record.py      QueryRecord(n, sql, params, duration_ms, rows, kind, origin, ...)
```

### Canal ssr (panel HTML)

HTML autocontenido y sin dependencias, que es un requisito y no un estilo: el panel tiene que funcionar cuando lo roto es justo la configuración que si no leería.

```text
debug/html.py        render_report_html / render_report_page
the panel is BILINGUAL by design: debug/assets/js/language.js holds LANG = { ES, EN }
that exemption covers the text TABLE, not the file: its comments are English
```

### Canal envelope

El informe añadido a la respuesta JSON. Está en `RISKY_CHANNELS`: devuelve SQL al cliente, así que `allowed_channels()` lo expulsa en producción.

```text
contrib/deliver.py   folds report().to_dict() into the JSON body
debug/channel.py     SnakeDebugChannel.ENVELOPE, inside RISKY_CHANNELS
```

### Canal timing (Server-Timing)

Una cabecera estándar, así que las devtools de cualquier navegador la leen sin panel ninguno. Lleva las tres duraciones por separado, porque `app` es `wall - db - mapping` y juntarlas esconde adónde se fue el tiempo.

```text
debug/timing.py      Server-Timing: db;dur=..., map;dur=..., app;dur=...
isolating MAPPING is what showed the cost was hydration and not the query
```

### Canal sidecar

El informe completo servido en su propia URL tras un token, así que la respuesta queda limpia. También en `RISKY_CHANNELS`.

```text
contrib/sidecar.py   GET /__snake__/{token} -> render_report_page(...)
debug/channel.py     SnakeDebugChannel.SIDECAR, inside RISKY_CHANNELS
```

### Canal otel (spans OTLP)

Spans a un tracer de verdad por OTLP/HTTP, usando los nombres de variable PROPIOS de OpenTelemetry — quien haya configurado otro exportador ya los tiene puestos. Un fallo de transporte no llega nunca al llamante: los spans se pierden y se avisa una vez.

```text
debug/otel/exporter.py   POSTs to OTEL_EXPORTER_OTLP_ENDPOINT
debug/otel/spans.py      one span per statement, db.system.name from the backend enum
a failed export warns ONCE and stays quiet after: telemetry must not break the request
```

### Asesor de índices

Lee el SQL EMITIDO contra la metadata y dice qué columna de filtro o de FK parece sin índice. No ejecuta `EXPLAIN`: adivina desde la sentencia, mientras que `explain()` le pregunta al motor — dos preguntas distintas que se acompañan bien.

```text
advisor.py           index_hints_from_sql / index_hints_from_records(min_ms=...)
                     regex over the emitted SQL + the declared metadata
contrib/deliver.py   wires the hints into the debug panel
```

### Página de error del ORM

NO implementada, y el prerequisito es la mitad cara: casi ninguna clase de `core/exceptions.py` tiene `__init__` ni un solo atributo —`SnakeIntegrityError` es la única excepción—, así que el `Cap` que rechazó una operación se funde en un f-string y se tira.

```text
not implemented. The order it would go in:
  1. structured data on the exceptions       the expensive part, 19 classes
  2. exc.add_note(...)  (PEP 678)            appears in Django's page, the admin
                                             email and the console, subclassing nothing
  3. a channel of its own reusing render_report_page
it enters RISKY_CHANNELS the same day it is declared: an error page carries SQL
```

## Integración

### Contrib WSGI / ASGI / Django

El núcleo es agnóstico del framework y los adaptadores son delgados: abrir el ámbito de captura, ejecutar la petición, entregar por el canal configurado. Las cabeceras ASGI tienen que ser ASCII — una no-ASCII rompió el cliente de test de Starlette, y por eso las etiquetas del panel no viajan nunca en cabecera.

```text
contrib/wsgi.py + contrib/asgi.py   middleware: open scope, deliver, close
contrib/django.py                   translates DATABASES into SnakeConnectionConfig
contrib/config.py                   open_session(config) wraps with CaptureDriver
headers stay ASCII: latin-1 is the ASGI spec's encoding for them
```

### CLI (esquema y migraciones)

Las órdenes resuelven la conexión ANTES de mirar el directorio de migraciones, así que «no hay migraciones» puede nombrar de qué base de datos habla — un mensaje que llegó a ser cierto e inútil a la vez.

```text
cli/                 makemigrations / migrate / rollback / status / fresh / squash
                     scaffold / check / advise / tables / table / dto
                     the DSN is resolved first: the message names the connection
core/config.py       DB_* is the public contract, read here and by the demos
```
