# Roadmap — qué hay y cómo de cubierto está

Esto es un ÍNDICE, no una guía: dice QUÉ hay y cuánta red lo sostiene, nunca cómo funciona — de eso
se encarga `docs/users/`, y tampoco es un plan.

**Escala** — *testeo*: `*` se aserta la cadena de SQL emitida · `**` se EJECUTA y se comprueban las
FILAS en un motor · `***` en los TRES, o el que no puede lo declara en `Cap`. *contrib*
(`docs/contributors/`) y *guía de usuario* (`docs/users/`): `*` mencionado · `**` sección propia ·
`***` sección propia con bloque de código. Sin estrellas = EN CONSTRUCCIÓN · `-` = pendiente (no
implementado o no escrito) · `?` = sin decidir.

**La cuarta columna, *demo*, y contesta lo que las otras tres no pueden.** Testeo dice que está
sostenida; contrib y la guía, que está escrita. Ninguna dice si **un usuario de las demos la
ejercita alguna vez** — y ésa es otra pregunta, con una respuesta incómoda.

| | *demo* |
|---|---|
| `-` | ninguna demo la toca |
| `*` | vive en el dominio compartido y NINGUNA ruta le abre puerta |
| `**` | una ruta la alcanza en una o dos de las tres |
| `***` | una ruta la alcanza en las TRES, así que React —que consume las tres APIs— también llega |

Se CALCULA, no se escribe a mano: `frameworks/shared/tests/demo_column.py` recorre el grafo de
llamadas desde cada ruta y cada módulo de cada demo, y un test aserta que esta tabla es igual a lo
que encuentra. Una columna mantenida a mano sería un quinto sitio que olvidar.

**Por qué alcance y no «¿la nombra esta app?».** Las tres demos comparten una sola capa de consultas
a propósito —modelos y selectores escritos una vez, y cada app los reexporta—, así que preguntar si
`fastapi/apps/` contiene `.filter(` mide la arquitectura y no la funcionalidad: contesta que no
justamente porque el diseño funciona. Por eso `*` y `**` suelen estar vacías: con la capa
compartida, lo que una ruta alcanza suele alcanzarse desde las tres a la vez.

**Qué significa `***` cuando «los tres» no es una frase.** `en los TRES` se lee bien para una
consulta y no dice nada de una fila cuyo SUJETO es un motor, o ninguno. Esa lectura se escribe aquí
porque se ha redescubierto dos veces; no es un listón más bajo, es el mismo listón aplicado a lo que
la fila trata:

| la fila trata de | `***` significa |
|---|---|
| algo que hacen los tres | ejecutado en los tres, o el que no puede lo declara en `Cap` |
| UN motor (`dialecto SQLite`, `introspección de MySQL`, `RebuildTable`) | ejecutado contra ESE motor, con lo que no puede declarado y asertado |
| ningún motor (el tipado, un canal de debug) | ejercitado de punta a punta por la herramienta que puede juzgarlo — mypy Y pyright para el tipado, un informe renderizado para un canal |
| algo que NO existe (`búsqueda de texto completo`) | un test aserta la AUSENCIA, así que el día que se implemente la afirmación se pone roja en vez de quedarse callada y falsa |

La última fila es la que merece la pena guardar: un límite que sigue escrito después de dejar de ser
cierto es la misma clase de mentira que una cifra que nadie relee.

**Aquí no hay cifras — la estrella es un nivel cualitativo, no una cantidad.** `***` no significa
«muchos tests», significa los tres motores, o que el que no puede lo declara en `Cap`. Las cuentas
son de `coverage`, y no se solapan: **`coverage` mide si una línea SE EJECUTÓ; la estrella mide QUÉ
SE COMPROBÓ.** Cobertura alta junto a una estrella es la combinación peligrosa —mucho código
ejecutado y nada verificado—, y es exactamente lo que esta tabla existe para enseñar.

**Cada celda es un enlace, y ése es el sentido de esta página.** Una afirmación y su prueba, a un
clic. Cuatro direcciones de salida por fila:

| el nombre | *testeo* | *contrib* | *guía de usuario* |
|---|---|---|---|
| el CÓDIGO que lo implementa | el TEST que lo sostiene | la decisión | cómo se usa |

Dos reglas evitan que esto se pudra. **Anclas, nunca números de línea** — `pagina.md#seccion`
sobrevive a una edición, `fichero.py:694` no; cuando una celda apunta a código, apunta al FICHERO. Y
**una celda con estrella y sin enlace es una mentira que se ve**: si dice `**` y no sabe apuntar a una
página, la estrella está mal. Las que van sin enlace se leen así, no como un descuido.

> **`--strict` no es la red de esta tabla.** `mkdocs.yml` excluye `planning/`, así que esta página no
> se construye nunca y sus enlaces no se resuelven jamás. Un enlace roto a propósito desde aquí dejó
> `uv run mkdocs build --strict` en **exit 0** y ni siquiera apareció en el log; el mismo enlace roto
> desde `docs/users/reference/limits.md` tumbó el build con **exit 1**. Lo que los sostiene es
> `src/test/test_links_the_site_never_builds.py`, un test por enlace, que cubre los tres sitios que
> el sitio no construye: este directorio y los dos ficheros de la raíz.

> **Los enlaces en rojo son la lista de pendientes, y están puestos a propósito.** Esta página apunta
> a ficheros que todavía no existen. El enlace se escribe igual: así la red nombra uno por uno lo que
> falta traducir, en vez de dejarlo en la cabeza de alguien.

Adónde apunta esto: las decisiones están en [la arquitectura](contributors/architecture.es.md),
cómo correr la suite en [testing](contributors/testing.es.md), el uso en
[la guía de usuario](users/getting-started/installation.es.md), y la puerta de entrada es
[el README](../README.es.md). Los planes de trabajo no están en este repositorio: son notas para
quien construya lo siguiente, cambian mientras se ejecutan, y un plan guardado al lado de un producto
publicado se lee como una promesa.

| funcionalidad | testeo | contrib | guía de usuario | demo |
|---|---|---|---|---|
| **CONSULTAS** |  |  |  |  |
| [`filter()`  / condiciones](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#filter-y-las-condiciones) | [`***`](users/getting-started/querying.es.md#filtrar) | `***` |
| [`order_by` / `limit` / `offset`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#order-by-limit-offset) | [`***`](users/getting-started/querying.es.md#ordenar-paginar-deduplicar) | `***` |
| [`distinct`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#distinct) | [`***`](users/getting-started/querying.es.md#ordenar-paginar-deduplicar) | `***` |
| [`group_by` / `having`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#group-by-having) | [`***`](users/getting-started/querying.es.md#proyectar-y-agregar) | `***` |
| [agregados (`count` `sum` `avg` `min` `max`)](../src/snakeorm/sql/aggregate.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#agregados-count-sum-avg-min-max) | [`***`](users/reference/api/queries.es.md#agregados) | `***` |
| [`string_agg`](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#string-agg) | [`***`](users/reference/api/queries.es.md#agregados) | `***` |
| [`annotate()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.es.md#annotate) | [`***`](users/getting-started/querying.es.md#proyectar-y-agregar) | `***` |
| [`join()` explícito](../src/snakeorm/sql/joins.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.es.md#join-explicito) | [`***`](users/guide/relationships.es.md#meter-una-coleccion-en-la-proyeccion-con-join) | `***` |
| [`include()` (to-one y to-many)](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/architecture.es.md#relaciones-donde-se-construye-el-grafo) | [`***`](users/guide/relationships.es.md#cargar) | `***` |
| [navegación profunda tipada (`A.b.c.d`)](../src/snakeorm/expressions/paths.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/architecture.es.md#tipado-y-proxy-de-runtime-el-corazon) | [`***`](users/reference/typing.es.md#la-recursion) | `-` |
| [`.any()` / correlated `exists`](../src/snakeorm/sql/condition.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.es.md#any-exists-correlado) | [`***`](users/guide/relationships.es.md#existencia) | `***` |
| [subconsulta escalar correlacionada](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_relationships_e2e.py) | [`***`](contributors/internals.es.md#subconsulta-escalar-correlada) | [`***`](users/guide/advanced-queries.es.md#subconsultas-escalares) | `***` |
| [`IN` compuesto (`snake_keys`)](../src/snakeorm/expressions/keys.py) | [`***`](../src/test/integration/test_composite_in_e2e.py) | [`***`](contributors/internals.es.md#in-compuesto-snake-keys) | [`***`](users/guide/advanced-queries.es.md#in-compuesto) | `***` |
| [`only()` / `defer()`](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#only-defer) | [`***`](users/getting-started/querying.es.md#traer-media-fila) | `***` |
| [`iterate()` (cursor de servidor)](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.es.md#iterate-cursor-de-servidor) | [`***`](users/getting-started/querying.es.md#recorrer-mucho-sin-cargarlo-todo) | `***` |
| [`CASE` / `COALESCE` / `NULLIF`](../src/snakeorm/expressions/conditional.py) | [`***`](../src/test/integration/test_scalar_expressions_e2e.py) | [`***`](contributors/internals.es.md#case-coalesce-nullif) | [`***`](users/guide/advanced-queries.es.md#expresiones-condicionales) | `***` |
| [funciones de ventana (`OVER`, marco)](../src/snakeorm/expressions/window.py) | [`***`](../src/test/integration/test_window_e2e.py) | [`***`](contributors/internals.es.md#funciones-de-ventana-over-frame) | [`***`](users/guide/advanced-queries.es.md#funciones-de-ventana) | `***` |
| [`UNION` / `INTERSECT` / `EXCEPT`](../src/snakeorm/query/compound.py) | [`***`](../src/test/query/test_compound.py) | [`***`](contributors/internals.es.md#union-intersect-except) | [`***`](users/guide/advanced-queries.es.md#compuestas-union-intersect-except) | `***` |
| [`WITH RECURSIVE`](../src/snakeorm/query/recursive.py) | [`***`](../src/test/integration/test_recursive_e2e.py) | [`***`](contributors/internals.es.md#with-recursive) | [`***`](users/guide/advanced-queries.es.md#recursivas-with-recursive) | `***` |
| [funciones de texto (`LOWER` `UPPER` `TRIM` `LENGTH` `CONCAT` `SUBSTRING` `REPLACE`)](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_scalar_expressions_e2e.py) | [`***`](contributors/internals.es.md#funciones-de-texto) | [`***`](users/reference/api/queries.es.md#funciones-de-texto) | `***` |
| [funciones de fecha (`DATE_TRUNC` `EXTRACT`)](../src/snakeorm/expressions/functions.py) | [`***`](../src/test/integration/test_date_functions_e2e.py) | [`***`](contributors/internals.es.md#funciones-de-fecha) | [`***`](users/reference/api/queries.es.md#funciones-de-fecha) | `***` |
| [`ABS` / `ROUND`](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_maths_functions_e2e.py) | [`***`](contributors/internals.es.md#abs-y-round) | [`***`](users/reference/api/queries.es.md#redondeo-y-magnitud) | `***` |
| [`CEIL` / `FLOOR` / `SQRT` / `POWER`](../src/snakeorm/expressions/scalar.py) | [`***`](../src/test/integration/test_maths_functions_e2e.py) | [`***`](contributors/internals.es.md#ceil-floor-sqrt-y-power) | [`***`](users/reference/api/queries.es.md#matematicas-que-dependen-del-build) | `***` |
| [`json_get()`](../src/snakeorm/expressions/expression.py) | [`***`](../src/test/integration/test_json_access_e2e.py) | [`***`](contributors/internals.es.md#json-get) | [`***`](users/getting-started/querying.es.md#leer-dentro-de-una-columna-json) | `***` |
| operadores JSON (contención, ruta) | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.es.md#operadores-json-de-contencion-y-ruta) | [`***`](users/reference/limits.es.md#lo-que-directamente-no-hay) | `-` |
| operadores de array | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.es.md#operadores-de-array) | [`***`](users/reference/limits.es.md#lo-que-directamente-no-hay) | `-` |
| búsqueda de texto completo | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.es.md#busqueda-de-texto-completo) | [`***`](users/reference/limits.es.md#lo-que-directamente-no-hay) | `-` |
| [`ILIKE`](../src/snakeorm/sql/condition.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.es.md#ilike) | [`***`](users/getting-started/querying.es.md#filtrar) | `***` |
| [`for_update()` (bloqueo de filas)](../src/snakeorm/query/query.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.es.md#for-update-bloqueo-de-fila) | [`***`](users/guide/advanced-queries.es.md#bloqueo-de-filas) | `***` |
| [`raw()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_query_basics_e2e.py) | [`***`](contributors/internals.es.md#raw) | [`***`](users/guide/advanced-queries.es.md#sql-crudo) | `-` |
| **ESCRITURAS** |  |  |  |  |
| [`insert` / `update` / `delete`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.es.md#insert-update-delete) | [`***`](users/getting-started/querying.es.md#escribir) | `***` |
| [`upsert`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/architecture.es.md#componentes) | [`***`](users/getting-started/querying.es.md#escribir) | `***` |
| [escrituras masivas (`bulk`)](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.es.md#escrituras-masivas) | [`***`](users/getting-started/querying.es.md#escribir) | `***` |
| [`RETURNING`](../src/snakeorm/sql/insert.py) | [`***`](../src/test/scenarios/test_returning_wide.py) | [`***`](contributors/internals.es.md#returning) | [`***`](users/guide/transactions.es.md#escrituras-que-preguntan-que-paso) | `***` |
| [`savepoint()` / `set_isolation()`](../src/snakeorm/session/isolation.py) | [`***`](../src/test/integration/test_concurrency_controls_e2e.py) | [`***`](contributors/internals.es.md#savepoint-set-isolation) | [`***`](users/guide/transactions.es.md#savepoints) | `***` |
| [reintento ante conflicto transitorio (`with_retry`)](../src/snakeorm/session/retry.py) | [`***`](../src/test/integration/test_retry_e2e.py) | [`***`](contributors/internals.es.md#with-retry) | [`***`](users/guide/transactions.es.md#reintentar-un-conflicto-de-serializacion) | `-` |
| [fallos de restricción (`SnakeIntegrityError`)](../src/snakeorm/drivers/failures.py) | [`***`](../src/test/integration/test_driver_failures_e2e.py) | [`***`](contributors/internals.es.md#fallos-de-restriccion) | [`***`](users/reference/api/errors.es.md#restricciones) | `-` |
| [`refresh()`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_writes_e2e.py) | [`***`](contributors/internals.es.md#refresh) | [`***`](users/guide/transactions.es.md#recargar-desde-la-base) | `***` |
| **MODELO Y TIPOS** |  |  |  |  |
| [descriptores tipados (`SnakeColumn` / `SnakeToOne` / `SnakeToMany`)](../src/snakeorm/fields/typed.py) | [`***`](../src/test/fields/test_typed_specifiers.py) | [`***`](contributors/architecture.es.md#tipado-y-proxy-de-runtime-el-corazon) | [`***`](users/reference/api/models.es.md#descriptores) | `***` |
| [`@dataclass_transform` on `@snake_model`](../src/snakeorm/decorators/model.py) | [`***`](../src/test/typing/test_type_checkers.py) | `***` | [`***`](users/reference/typing.es.md#el-constructor) | `***` |
| [PK y FK COMPUESTAS](../src/snakeorm/metadata/primary_key.py) | [`***`](../src/test/integration/test_composite_chain_e2e.py) | [`***`](contributors/architecture.es.md#metadata-pkfk-con-una-estructura) | [`***`](users/guide/columns.es.md#claves-primarias) | `-` |
| [herencia polimórfica](../src/snakeorm/decorators/polymorphic.py) | [`***`](../src/test/integration/test_model_behaviour_e2e.py) | [`***`](contributors/internals.es.md#herencia-polimorfica) | [`***`](users/guide/inheritance.es.md#polimorfica) | `***` |
| [vistas (`@snake_view`)](../src/snakeorm/decorators/view.py) | [`***`](../src/test/integration/test_compound_as_view.py) | [`***`](contributors/internals.es.md#vistas-snake-view) | [`***`](users/reference/api/models.es.md#modelo-y-vista) | `***` |
| [señales y triggers](../src/snakeorm/core/signals.py) | [`***`](../src/test/integration/test_model_behaviour_e2e.py) | [`***`](contributors/internals.es.md#senales-y-disparadores) | [`***`](users/guide/signals-and-triggers.es.md) | `-` |
| [índices y restricciones](../src/snakeorm/fields/index.py) | [`***`](../src/test/integration/test_indexes_e2e.py) | [`***`](contributors/internals.es.md#indices-y-restricciones) | [`***`](users/guide/indexes-and-constraints.es.md) | `***` |
| [índices parciales](../src/snakeorm/fields/index.py) | [`***`](../src/test/migration/test_partial_indexes_per_engine.py) | [`***`](contributors/internals.es.md#indices-parciales) | [`***`](users/guide/indexes-and-constraints.es.md#indices-parciales) | `-` |
| [métodos de índice (`GIN` / `GIST` / `BRIN`)](../src/snakeorm/metadata/index_method.py) | [`***`](../src/test/integration/test_indexes_e2e.py) | [`***`](contributors/internals.es.md#metodos-de-indice-gin-gist-brin) | [`***`](users/guide/indexes-and-constraints.es.md#metodo-de-indice) | `-` |
| [comentarios (`db_comment`)](../src/snakeorm/metadata/table.py) | [`***`](../src/test/migration/test_comments.py) | [`***`](contributors/internals.es.md#comentarios-db-comment) | [`***`](users/guide/columns.es.md#comentarios) | `-` |
| [conversores de tipo (`register_converter`)](../src/snakeorm/core/converters.py) | [`***`](../src/test/integration/test_type_round_trip.py) | [`***`](contributors/internals.es.md#convertidores-de-tipo-register-converter) | [`***`](users/guide/columns.es.md#un-tipo-que-el-orm-no-trae) | `-` |
| [helpers de UTC (`SnakeUtc`, `utc_now`, `to_utc`)](../src/snakeorm/times.py) | [`***`](../src/test/integration/test_utc_helpers_e2e.py) | [`***`](contributors/internals.es.md#helpers-utc-snakeutc-utc-now-to-utc) | [`***`](users/guide/columns.es.md#cuatro-ayudantes-y-por-que-no-son-datetimenow) | `***` |
| **MOTORES** |  |  |  |  |
| [PostgreSQL dialect](../src/snakeorm/dialects/postgres.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.es.md#multi-motor-tres-ejes) | [`***`](users/engines/dialects.es.md) | `***` |
| [MySQL / MariaDB dialect](../src/snakeorm/dialects/mysql.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.es.md#multi-motor-tres-ejes) | [`***`](users/engines/dialects.es.md) | `***` |
| [SQLite dialect](../src/snakeorm/dialects/sqlite.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/architecture.es.md#multi-motor-tres-ejes) | [`***`](users/engines/dialects.es.md) | `***` |
| [catálogo `Cap` (`Full` / `Degraded` / `Nope`)](../src/snakeorm/dialects/capabilities.py) | [`***`](../src/test/dialects/test_capabilities.py) | [`***`](contributors/architecture.es.md#el-catalogo-de-capacidades) | [`***`](users/engines/dialects.es.md#el-catalogo-de-capacidades) | `***` |
| [aviso de salvedades al arrancar](../src/snakeorm/dialects/capabilities.py) | [`***`](../src/test/integration/test_the_catalogue_does_not_lie.py) | [`***`](contributors/internals.es.md#aviso-de-salvedades-al-arrancar) | [`***`](users/engines/dialects.es.md#como-funciona-de-verdad-el-aviso-al-arrancar) | `***` |
| [drivers síncronos (psycopg2, PyMySQL, sqlite3)](../src/snakeorm/drivers/base.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.es.md#drivers-sincronos) | [`***`](users/getting-started/installation.es.md#el-driver-de-tu-motor) | `***` |
| [drivers asíncronos (psycopg 3 nativo + dos sobre un hilo)](../src/snakeorm/drivers/asyncbase.py) | [`***`](../src/test/integration/test_async_session_lifecycle.py) | [`***`](contributors/internals.es.md#drivers-asincronos) | [`***`](users/engines/async.es.md#tres-motores-tres-drivers-asincronos) | `***` |
| [pool de conexiones (`pre_ping`, `recycle`, timeout)](../src/snakeorm/drivers/pool.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.es.md#pool-de-conexiones) | [`***`](users/engines/multi-connection.es.md#un-pool-que-sobrevive-a-un-despliegue) | `***` |
| [timeout de sentencia](../src/snakeorm/drivers/timeout.py) | [`***`](../src/test/integration/test_statement_timeout_e2e.py) | [`***`](contributors/internals.es.md#timeout-de-sentencia) | [`***`](users/guide/transactions.es.md#en-produccion-envolver-el-driver) | `-` |
| [driver de logging](../src/snakeorm/drivers/logging.py) | [`***`](../src/test/integration/test_the_composed_stack.py) | [`***`](contributors/internals.es.md#driver-de-logging) | [`***`](users/guide/transactions.es.md#en-produccion-envolver-el-driver) | `-` |
| `notices` / `statusmessage` del servidor | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/architecture.es.md#donde-va-una-funcionalidad-encima-de-la-costura-o-debajo) | [`***`](users/reference/limits.es.md#lo-que-directamente-no-hay) | `-` |
| [`EXPLAIN`](../src/snakeorm/session/session.py) | [`***`](../src/test/integration/test_explain_e2e.py) | [`***`](contributors/architecture.es.md#donde-va-una-funcionalidad-encima-de-la-costura-o-debajo) | [`***`](users/guide/debugging.es.md#pedirle-el-plan-al-motor-explain) | `***` |
| **MIGRACIONES** |  |  |  |  |
| [`diff` y autodetección](../src/snakeorm/migration/autodetect.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.es.md#diff-y-autodeteccion) | [`***`](users/getting-started/migrations.es.md#que-detecta-el-autogen) | `-` |
| [runner (atómico por migración)](../src/snakeorm/migration/runner.py) | [`***`](../src/test/migration/test_atomicity.py) | [`***`](contributors/internals.es.md#runner-atomico-por-migracion) | [`***`](users/getting-started/migrations.es.md#atomicidad) | `-` |
| [`RebuildTable` (la salida de SQLite)](../src/snakeorm/migration/operations.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.es.md#rebuildtable-la-salida-de-sqlite) | [`***`](users/reference/api/migrations.es.md#operaciones-de-tabla) | `-` |
| [`RunPython` (datos, con reverso)](../src/snakeorm/migration/operations.py) | [`***`](../src/test/integration/test_migration_cycle_e2e.py) | [`***`](contributors/internals.es.md#runpython-datos-con-reverso) | [`***`](users/getting-started/migrations.es.md#migraciones-de-datos) | `-` |
| [colapsado (`squash`)](../src/snakeorm/migration/squash.py) | [`***`](../src/test/integration/test_migration_shapes_e2e.py) | [`***`](contributors/internals.es.md#colapso-squash) | [`***`](users/getting-started/migrations.es.md#colapsar-el-historico) | `-` |
| [dependencias entre apps](../src/snakeorm/migration/loader.py) | [`***`](../src/test/migration/test_loader.py) | [`***`](contributors/internals.es.md#dependencias-entre-apps) | [`***`](users/reference/api/migrations.es.md#runners) | `-` |
| [emisores DDL × motor (la matriz)](../src/snakeorm/migration/ddl.py) | [`***`](../src/test/migration/test_emitter_dialect_matrix.py) | [`***`](contributors/internals.es.md#emisores-ddl-por-motor-la-matriz) | [`***`](users/engines/dialects.es.md#traduccion-vs-rechazo) | `-` |
| **DB-FIRST** |  |  |  |  |
| [introspección de PostgreSQL](../src/snakeorm/introspection/postgres.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.es.md#introspeccion-de-postgresql) | [`***`](users/engines/db-first.es.md#que-genera) | `-` |
| [introspección de MySQL](../src/snakeorm/introspection/mysql.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.es.md#introspeccion-de-mysql) | [`***`](users/engines/db-first.es.md#que-genera) | `-` |
| [introspección de SQLite](../src/snakeorm/introspection/sqlite.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.es.md#introspeccion-de-sqlite) | [`***`](users/engines/db-first.es.md#que-genera) | `-` |
| [andamiaje de modelos](../src/snakeorm/introspection/models.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.es.md#scaffold-de-modelos) | [`***`](users/engines/db-first.es.md#no-hay-adopcion-in-situ) | `-` |
| [detección de deriva contra la BD viva](../src/snakeorm/introspection/drift.py) | [`***`](../src/test/integration/test_db_first_e2e.py) | [`***`](contributors/internals.es.md#deteccion-de-deriva) | [`***`](users/engines/db-first.es.md#deteccion-de-deriva) | `-` |
| **DEBUG** |  |  |  |  |
| [colector y `DebugReport`](../src/snakeorm/debug/collector.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#colector-y-debugreport) | [`***`](users/guide/debugging.es.md#inspeccionar-el-informe) | `***` |
| [`ssr` channel (panel HTML)](../src/snakeorm/debug/html.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#canal-ssr-panel-html) | [`***`](users/guide/debugging.es.md#los-canales) | `***` |
| [`envelope` channel](../src/snakeorm/contrib/deliver.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#canal-envelope) | [`***`](users/guide/debugging.es.md#la-forma-del-envelope) | `***` |
| [`timing` channel (`Server-Timing`)](../src/snakeorm/contrib/deliver.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#canal-timing-server-timing) | [`***`](users/guide/debugging.es.md#los-canales) | `***` |
| [`sidecar` channel](../src/snakeorm/contrib/sidecar.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#canal-sidecar) | [`***`](users/guide/debugging.es.md#los-canales) | `***` |
| [`otel` channel (OTLP spans)](../src/snakeorm/debug/channel.py) | [`***`](../src/test/integration/test_debug_channels_e2e.py) | [`***`](contributors/internals.es.md#canal-otel-spans-otlp) | [`***`](users/guide/debugging.es.md#el-canal-otel-spans-para-un-trazador-de-verdad) | `***` |
| [asesor de índices](../src/snakeorm/advisor.py) | [`***`](../src/test/test_advisor.py) | [`***`](contributors/internals.es.md#asesor-de-indices) | [`***`](users/guide/indexes-and-constraints.es.md#que-indice-falta-snakeorm-advise) | `-` |
| página de error del ORM | [`***`](../src/test/test_limits_are_true.py) | [`***`](contributors/internals.es.md#pagina-de-error-del-orm) | [`***`](users/reference/limits.es.md#lo-que-directamente-no-hay) | `-` |
| **INTEGRACIÓN** |  |  |  |  |
| [WSGI / ASGI / Django contrib](../src/snakeorm/contrib/wsgi.py) | [`***`](../src/test/integration/test_contrib_middleware_e2e.py) | [`***`](contributors/internals.es.md#contrib-wsgi-asgi-django) | [`***`](users/guide/debugging.es.md#enchufarlo-al-framework-una-linea) | `***` |
| [CLI (esquema y migraciones)](../src/snakeorm/cli/app.py) | [`***`](../src/test/integration/test_cli_three_engines_e2e.py) | [`***`](contributors/internals.es.md#cli-esquema-y-migraciones) | [`***`](users/getting-started/migrations.es.md) | `-` |
