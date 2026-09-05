# Arquitectura (v2)

```python
from __future__ import annotations

from snakeorm import (
    SnakeColumn, SnakeModel, SnakeQuery, SnakeToOne,
    snake_auto, snake_int, snake_link, snake_model, snake_str, snake_to_one,
)

@snake_model(table="countries")
class Country(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()

@snake_model(table="cities")
class City(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[Country] = snake_to_one(country_id)
    name: SnakeColumn[str] = snake_str()

snake_link()  # the classes are already compiled; this resolves the relationships

# The query is an immutable AST: it does not execute. The JOIN comes from the relationship path.
q = SnakeQuery(City).filter(City.country.name == "España")
```

Ese es el pipeline entero: **clase Python → metadata inmutable → AST → `(sql, params)` → driver**. La
clase se inspecciona una vez; el runtime lee del grafo, nunca de la clase.

## Principios (innegociables)

- **Type-first**: el tipo viene de Python. La metadata solo añade info SQL, nunca el tipo.
- **Compile-once**: la clase se inspecciona UNA vez → grafo inmutable. El runtime no reflexiona.
- **Cero `Any`** en la API, **cero SQL crudo** fuera de `sql/`, **cero magic strings**.
- Una responsabilidad por módulo. Sin metaclases gigantes.
- **El ORM da primitivas, no roles.** `Repository`/`Service`/`Selector` son de tu app; el ORM entrega
  el ladrillo (`SnakeQuery`).
- **Lo que un motor no da, se DECLARA; nunca se adivina.** O se traduce a un equivalente exacto, o el
  ORM para y dice por qué. Guardar peor y callarse no es una opción.

## Decisiones

| Decisión | Elección | Estado |
|----------|----------|--------|
| Tipado profundo de relaciones | Descriptores recursivos: acceso de clase → `SnakeExpr[T]` / `type[M]` / `SnakeCollection[M]` | ✅ mypy y pyright |
| Compilación | Compile-once → grafo inmutable | decidido |
| Ejecución | **Síncrona Y asíncrona**, sobre la misma costura incolora | ✅ implementado |
| Multi-motor | Tres ejes: **Dialect** / **Driver** / **Introspector** | ✅ Postgres, MySQL/MariaDB, SQLite |
| Diferencias entre motores | Declaradas en un catálogo de capacidades (`Cap` → `Full`/`Degraded`/`Nope`) | ✅ implementado |
| SQL | Siempre `(sql, params)`; nunca interpolar valores | decidido |
| Entrypoint de consultas | `SnakeQuery(Model)` (el entrypoint ES el tipo `SnakeQuery[T]`) | decidido |
| Enlazado | El decorador compila y registra suelto → `snake_link()` enlaza al final | ✅ probado |

## Pipeline

```text
   Python classes (@snake_model)              Model modules, imported
             │                                          │
             ▼                                          ▼
   Phase 1: compile_model()  ──────►  SnakeTableInfo registered LOOSE
   (compiler/, run by the decorator)   (registry/) — nothing is linked yet
             │
             ▼
   Phase 2: snake_link()  (linker/) — every model exists now:
            resolves types, pairs FKs, validates, links to-one then to-many
             │
             ▼
   Registry (IMMUTABLE, frozen graph)
             │                    everything below reads the GRAPH, NEVER the class
             ▼
   SnakeTableInfo / SnakeColumnInfo /   ┌────────────┬───────────────┬─────────────┐
   SnakePrimaryKeyInfo /             SnakeQuery      sql/            migration/
   SnakeForeignKeyInfo /             (AST)           (AST + Dialect → sql, params)
   SnakeRelationshipInfo                                  │
                                                          ▼
                                         session/planning.py → Plan (COLORLESS)
                                         sql + params + what to do with the rows
                                                          │
                                            ┌─────────────┴─────────────┐
                                            ▼                           ▼
                                      SnakeSession                 AsyncSession
                                      (SnakeDriver)                (AsyncDriver)
```

**Regla de oro**: todo cuelga del grafo. El grafo no sabe qué es Postgres ni conoce el runtime.

## Componentes

| Módulo | Responsabilidad única |
|--------|------------------------|
| `decorators/` | `@snake_model`, `@snake_view`, `@snake_abstract`, `@snake_db_first`, `@snake_trigger`, `@snake_function`, `@snake_result`, `@snake_row`: compilan la clase y la registran **suelta**. Sin lógica SQL. |
| `compiler/` | `compile_model()`: el paso "clase → metadata". Recorre los descriptores UNA vez y devuelve un `SnakeTableInfo` congelado. |
| `core/` | Lo que sostiene a todo lo demás y no depende de nada: `exceptions.py` (la jerarquía de `SnakeError`), `converters.py` (el registro del viaje del valor), `signals.py`, `placement.py` (en qué base y en qué esquema), `config.py`, `sentinels.py`. |
| `fields/` | El sistema de descriptores — la tesis del proyecto. `SnakeColumn`, `SnakeToOne`, `SnakeToMany` y los field specifiers (`snake_int`, `snake_str`, `snake_decimal`, `snake_json`, `snake_enum`, `snake_to_one`, …). |
| `metadata/` | Estructuras **frozen**: `SnakeTableInfo`, `SnakeColumnInfo`, `SnakePrimaryKeyInfo`, `SnakeForeignKeyInfo`, `SnakeRelationshipInfo`, y los enums agnósticos (`SnakeFkAction`, `SnakeIntSize`, `SnakeServerDefault`, …). |
| `registry/` | `SnakeRegistry`: el almacén de modelos compilados (clase → `SnakeTableInfo`). Entrada para migraciones, SQL y relaciones. |
| `linker/` | `snake_link()`: la fase 2. Resuelve tipos y relaciones, valida, y enlaza a-uno antes que a-muchos. |
| `expressions/` | `SnakeExpr[T]`, `SnakeCondition`, agregados, funciones escalares, `CASE`/`COALESCE`/`NULLIF`, funciones de ventana y el recolector de paths. |
| `query/` | DSL tipada: `SnakeQuery[T]`, `SnakeJoinedQuery`, composición (`UNION`/`EXCEPT`/`INTERSECT`) y `WITH RECURSIVE`. Construye AST, **no ejecuta**. |
| `sql/` | AST + `SnakeDialect` → `(sql, params)`. **Único** sitio que emite SQL. |
| `dialects/` | `SnakeDialect` Protocol + `PostgresDialect`, `MySQLDialect`, `SQLiteDialect`, y el catálogo de capacidades (`Cap`, `SnakeCapabilities`, `SnakeSyntax`, `SnakeLimits`). |
| `drivers/` | Los Protocols `SnakeDriver` / `AsyncDriver`, los drivers concretos, y los drivers **decoradores**: pool, logging, timeout y el puente sync→async por hilo. |
| `session/` | La ejecución: `SnakeSession`, `AsyncSession`, el `Plan` incoloro (`planning.py`), la hidratación de filas (`mapper.py`), coerción, guardas de pre-vuelo, reintento, niveles de aislamiento y la fábrica de sesiones. |
| `migration/` | El pipeline de migraciones: `autodetect` → `diff` → `operations` → `planner` → `render`/`loader` → `runner`/`asyncrunner`, más `ddl`, `state`, `squash`, `renames` y `realize`. |
| `introspection/` | El camino db-first: el Protocol `SnakeIntrospector` + implementaciones de Postgres, MySQL/MariaDB y SQLite, detección de deriva, y **scaffolding** de modelos (generación de código). |
| `dto/` | Formas de respuesta declaradas -> TypedDicts. `snake_dto(...)` se LEE del fichero del propio usuario con `ast` y no se ejecuta nunca; los tipos generados vuelven a una región marcada de ese mismo fichero, y nada de fuera se toca. Se importa de `snakeorm.dto`: la fachada no lo re-exporta. |
| `debug/` | El panel de depuración: driver que graba cada sentencia, colector por scope, `DebugReport` (dict, texto, `Server-Timing`, HTML) y el helper de test `assert_queries`. |
| `contrib/` | Los enlazadores de framework: ASGI, WSGI, middleware de Django, traducción compartida de config y el buffer del sidecar. |
| `cli/` | El comando `snakeorm`: `makemigrations`, `migrate`, `rollback`, `status`, `fresh`, `scaffold`, `check`, `squash`, `tables`, `table`, `advise`, `dto`. |
| `helpers/` | Utilidades pequeñas que comparten consumidores que no deben conocerse: anotaciones, recolección por MRO, literales Python seguros. |

Cuatro módulos viven en la raíz porque no son de ninguna capa: `model.py` (la base `SnakeModel`),
`connection.py` (el config de conexión centralizado), `times.py` (UTC sin zonas adivinadas) y
`advisor.py` (el asesor de índices).

## Metadata: PK/FK con UNA estructura

Simple y compuesta comparten estructura. Sin casos especiales.

```text
SnakePrimaryKeyInfo.columns : tuple[...]      # 1 = simple, N = composite
SnakeForeignKeyInfo.pairs   : tuple[(local, remote), ...]   # 1 pair = simple, N = composite
```

`pairs` empareja las columnas locales del `snake_to_one(...)` con la PK del destino **por posición**.
El join AND-ea todos los pares. **Mismo código para simple y compuesta.**

## Compilar y enlazar (resistente a circulares)

Con `City ↔ Country`, al definir `City` la clase `Country` aún no existe. Solución (patrón
`pg_dump` / EF Core): **registrar todo primero, enlazar al final.**

- **Fase 1 — el decorador.** `@snake_model` llama a `compile_model()`, que recorre los descriptores y
  produce el `SnakeTableInfo` congelado: columnas, PK, índices, checks. Lo registra **suelto**; no
  enlaza nada (las circulares ni se enteran). Las anotaciones de relación que todavía no resuelven se
  saltan a propósito: aquí solo importan las columnas.
- **Fase 2 — `snake_link()`.** Corre cuando todo existe: `get_type_hints()` resuelve los destinos,
  las FKs se emparejan contra la PK del destino **por posición**, y el emparejamiento se valida
  (mismo número de columnas, tipos Python que casan) → errores AQUÍ, al arrancar (fail-fast). Dos
  pasadas: primero a-uno (FK) y después a-muchos (las inversas, que leen la FK ya resuelta del hijo).
  Es idempotente.
- **Requisito**: los ficheros de modelos empiezan con `from __future__ import annotations` (las
  anotaciones son strings perezosos → sin `NameError` al definir).
- **MANUAL, y a propósito**: nadie dispara la fase 2 por ti. Llamas a `snake_link()` una vez, después
  de importar los módulos de modelos. El ORM no engancha `__init_subclass__` ni un import hook para
  adivinar cuándo «ya existe todo», porque no puede saberlo: el sentido de la fase 1 es justamente
  que un modelo puede seguir esperando a un módulo que nadie ha importado todavía, y un enlazado
  disparado antes de tiempo resolvería medio grafo y lo daría por bueno. Así que olvidar la llamada
  es un error normal, y tiene excepción propia en vez de un `AttributeError`:
  `SnakeUnlinkedRelationship`, que levanta el descriptor con la frase «call `snake_link()` first».
  La CLI es la única excepción: importa los modelos y la llama ella misma antes de diffear o de
  emitir DDL.

## Relaciones — dónde se construye el grafo

Las resuelve `linker/`: casa cada destino declarado contra el registro y levanta al arrancar si no
encuentra uno (`SnakeRegistryError`: «which is not registered (did you import it?).»), así que una
relación sin enlazar nunca es un `AttributeError` en ejecución.

CÓMO se declara —FK simple, FK compuesta por posición y el puente `through`/`via`/`to` de una
muchos-a-muchos— es documentación de usuario y vive en
[la guía de relaciones](../users/guide/relationships.es.md). Estaba copiada aquí, lo que significaba que
una de las dos envejecía antes y quien leía no tenía forma de saber cuál.

## Tipado y proxy de runtime — el corazón

La misma propiedad se comporta distinto según se mire desde la clase o la instancia — lo que eso le
da al lector está en [Cómo funciona el tipado](../users/reference/typing.es.md):

| Acceso | `SnakeColumn[T]` | `SnakeToOne[M]` | `SnakeToMany[M]` |
|--------|------------------|-----------------|------------------|
| Clase (`User.x`) | `SnakeExpr[T]` | `type[M]` | `SnakeCollection[M]` |
| Instancia (`u.x`) | `T` | `M` | `list[M]` |

**Tres descriptores, tres accesos de clase distintos**, y la tercera columna es la que lleva la
tesis. Una a-uno conserva la cardinalidad, así que el acceso de clase devuelve `type[M]` y la
navegación sigue sin más. Una a-muchos CAMBIA la cardinalidad, así que el acceso de clase devuelve
`SnakeCollection[M]`, que a propósito NO expone las columnas del hijo: solo `.any(...)` y los
agregados escalares. Eso es lo que convierte `Nation.makers.name` en un **error de tipos**
(`"SnakeCollection[Maker]" has no attribute "name"`) en vez de en la consulta que Django compila,
corre y te duplica las filas en silencio. Poner `type[M]` en esta columna describiría un ORM que
éste existe justamente para no ser.

`User.car.brand.name` → `SnakeExpr[str]` (profundo, tipado, sin plugin). Los campos del destino son
descriptores → la navegación se auto-envuelve. En runtime el objeto **acumula el path**, así que el
`SnakeCondition` conoce sus joins y **el compilador los genera solo** desde `SnakeForeignKeyInfo`.
Se consiguen las dos cosas que parecían incompatibles: tipado profundo Y joins automáticos.

## DSL de consultas

`SnakeQuery(Model)` **es** el tipo `SnakeQuery[T]`. Construye un AST inmutable; **no ejecuta**. La
ejecución vive en `SnakeSession` / `AsyncSession` (`session.all(q)`, `session.first(q)`, …). El
filtro es `.filter(...)`, no `.where()`.

```python
from snakeorm import SnakeQuery

q = SnakeQuery(City).filter(City.country.name == "España").order_by(City.name).limit(10)
```

Se tipa **sin plugin** (a diferencia del `objects` de Django, que obligó a `django-stubs`). El ORM
entrega la primitiva; los patrones de dominio (Repository, Service) los pones tú.

## Multi-motor: tres ejes

Tres motores, **los tres de primera clase**: PostgreSQL, MySQL/MariaDB y SQLite ([por qué la costura
aguanta](index.es.md)). Tres ejes, **nunca mezclados**:

| Eje | Qué decide | Protocol | Vive en |
|---|---|---|---|
| **Dialect** | Cómo se ESCRIBE el SQL: placeholders, quoting, `LIMIT/OFFSET`, `RETURNING`, upsert, mapeo de tipos Python→SQL | `SnakeDialect` | `dialects/` |
| **Driver** | Cómo se EJECUTA: la librería DBAPI, conexión, cursor, transacción | `SnakeDriver`, `AsyncDriver` | `drivers/` |
| **Introspector** | Cómo se LEE el esquema: qué tablas, columnas y FKs tiene ya una base viva | `SnakeIntrospector` | `introspection/` |

Y dentro del dialecto hay un cuarto corte, porque el dialecto no es una pieza monolítica:
**vocabulario frente a gramática**.

- **Vocabulario** — lo que el motor SABE HACER. Eso es el catálogo de capacidades de más abajo.
- **Gramática** — la FORMA de una sentencia que los tres motores saben ejecutar. `SnakeSyntax` vive en
  `dialects/capabilities.py` y lo leen los emisores: `migration/ddl.py` ramifica con
  `dialect.syntax.alter_column_style is AlterColumnStyle.MYSQL_MODIFY`, y el mismo objeto decide
  `DROP INDEX x` frente a `DROP INDEX x ON t`, el alcance del `DROP TRIGGER`, y cómo se escribe un
  `INSERT` que es todo valores por defecto. La gramática se **traduce** en el emisor y **nunca** para
  un plan.

Mezclar las dos cablea un emisor a la forma de un solo motor.

**El grafo y los modelos son 100% agnósticos del motor.** La emisión es siempre `(sql, params)`; los
valores nunca se interpolan en el string. Eso mata la inyección SQL Y es lo que habilita el
multi-motor: los placeholders son justo lo que cambia entre motores.

## El catálogo de capacidades

Lo que un usuario hace con él está en
[el catálogo de capacidades](../users/engines/dialects.es.md#el-catalogo-de-capacidades); esto es
cómo está construido.

`dialects/capabilities.py` es la abstracción central para tocar cualquier cosa multi-motor.
Sustituyó a veinte `supports_*` sueltos en el Protocol del dialecto, que se podían preguntar de UNO
en uno pero ni se podían **recorrer** (no se avisa de todo lo que le falta a un motor sin iterar la
lista) ni sabían decir **"a medias"** (SQLite guarda un `Decimal` y lo devuelve exacto, pero lo
ordena como TEXTO).

Tres piezas:

```python
from snakeorm.dialects.capabilities import Cap, Degraded, Full, Nope, SnakeCapabilities

caps = SnakeCapabilities(
    declared={
        Cap.RETURNING: Full(),
        Cap.DECIMAL_ORDERING: Degraded("SQLite stores NUMERIC as TEXT: it orders lexicographically"),
        Cap.ALTER_COLUMN: Nope("SQLite would need the whole table rebuilt"),
        # ... and the rest of the catalogue: leaving one out fails on import
    }
)
```

- **`Cap`** — el catálogo de todo lo que cualquier motor puede hacer. Dos familias: las
  **estructurales** (si faltan, la operación no se puede ejecutar) y las de **fidelidad de tipo**
  (nunca paran nada; el valor entra y sale exacto, y lo que se degrada es la semántica SQL: ordenar,
  comparar, operar).
- **`Support = Full | Degraded | Nope`** — el tri-estado. `Degraded` y `Nope` exigen un **motivo**, y
  se hace cumplir en el `__post_init__`: ese texto es lo que lee el usuario, no un comentario. La
  unión (en vez de un bool más un texto suelto) es lo que permite derivar de una sola fuente tanto la
  decisión del plan como el aviso, sin que puedan contradecirse.
- **`SnakeCapabilities`** — lo que UN motor contesta al catálogo ENTERO. Su `__post_init__`
  **revienta al importar** si un dialecto deja una entrada sin declarar, y después congela el mapa.
  Un `frozenset` de capacidades soportadas sería más corto de escribir y estaría mal: la que se te
  olvidó no está, y "no está" se lee como "no soportada" — un default silencioso, en el ORM que
  grita.

Sus lectores: `.can(cap)` contesta si el motor puede, **tratando `Degraded` como un sí** (tomarlo por
un no prohibiría un `Decimal` en SQLite, que lo guarda y lo devuelve exacto), y `.caveats()` devuelve
cada `(capacidad, motivo)` que no sea `Full`, en el orden del catálogo, que es lo que la sesión avisa
**una** vez por salvedad al abrirse.

El catálogo está partido en dos frozensets, y esa partición es lo que lo hace comprobable:

| Conjunto | Qué significa | Consecuencia |
|---|---|---|
| `PLAN_CAPS` | Alguien la lee para DECIDIR: para una operación o cambia la forma del SQL | Una capacidad de aquí que nadie lea es metadata muerta — falla `test_every_plan_capability_has_a_consumer` |
| `ADVISORY_CAPS` | Todo lo demás: se declara para AVISAR | La familia de fidelidad de tipo, más `INDEX_METHODS` (la hace cumplir el `index_method()` del propio dialecto) |

Junto a las capacidades viven `SnakeSyntax` (la gramática, arriba) y `SnakeLimits` — topes numéricos
donde `None` no significa "sin tope" sino "este motor ignora el parámetro declarado", que es la
respuesta honesta de SQLite. `limits.bind_params` es lo que hace que un `INSERT` masivo trocee en
lotes, y lo que dimensiona el select-in de `include()` — medido en MARCADORES, así que una clave
compuesta cuesta uno por columna y el filtro del prefetch gasta de la misma bolsa
(`session/planning.py:parents_per_batch`).

## El vocabulario de tipos: dos registros, dos preguntas

Ampliar los tipos que el ORM entiende son dos ejes independientes, y confundirlos es el error de
siempre:

| Pregunta | Dónde | Alcance |
|---|---|---|
| ¿Cómo se escribe la COLUMNA? | `dialect.register_type(python_type, sql)` | Por dialecto — el mismo tipo es `INET` en Postgres y `TEXT` en SQLite. Toca el DDL. |
| ¿Cómo VIAJA el valor? | `register_converter(python_type, to_db=…, from_db=…)` en `core/converters.py` | Global. Toca el viaje de ida y vuelta, no el esquema. |

El eje del valor puede permitirse ser global solo porque `from_db` es **idempotente**, y eso se
comprueba al REGISTRAR (`_demand_idempotent`), no en la primera lectura de producción. El motivo es
el multi-motor: el mismo conversor sirve para los tres motores y cada uno devuelve la columna en una
forma — Postgres puede entregar ya el objeto y SQLite el texto. `from_db` tiene que tragar las dos,
así que aplicarlo dos veces debe dar lo mismo que aplicarlo una.

El registro además se niega a reescribir los tipos que el ORM ya trata (`mark_builtin` los declara
desde `session/coercion.py`): un registro global lo comparte el proceso entero, y dejar que una
librería de terceros cambie cómo viaja un `Decimal` con solo importarse no es un punto de extensión,
es un accidente esperando.

Vive en `core/` porque lo consultan los dos extremos del viaje: `sql/adapt.py` al escribir y
`session/coercion.py` al leer. Cualquier otro sitio crearía un ciclo entre `sql/` y `session/`.

## Sync y async sobre la misma costura incolora

Los dos modos de ejecución están implementados y exportados: `SnakeSession` y `AsyncSession`,
`SnakeDriver` y `AsyncDriver`, seis drivers concretos, `migration/runner.py` y
`migration/asyncrunner.py`.

Lo que lo hizo posible es que **la generación de SQL no tiene color**: no ejecuta, así que se reutiliza
tal cual. La costura es `session/planning.py`, que guarda la única copia de las decisiones —qué SQL
emitir y cómo interpretar las filas que vuelvan—:

```text
Plan(sql, params, apply, needs_rows)
      │       │      │        └─ EXECUTE vs QUERY: known by whoever built the plan,
      │       │      │           never guessed from the string
      │       │      └─ rows → domain object (hydration, RETURNING write-back, casting)
      │       └─ never interpolated
      └─ built by sql/, engine-specific only through the dialect
```

Las funciones de `planning.py` devuelven `(sql, params, aplicar)` y **ninguna toca un driver**.
`SnakeSession` y `AsyncSession` quedan finas: pide el plan, ejecútalo, aplícalo. Copiar una sesión de
mil líneas con un `await` delante crearía dos sitios donde arreglar cada bug.

La paridad no se fía de la buena voluntad: las dos sesiones consumen el MISMO `Plan` y el mismo
catálogo de mensajes, y hay un test que compara el **mensaje** además del SQL. En un ORM cuya
doctrina es gritar, el mensaje ES el producto.

Los tres motores tienen driver async. El de Postgres habla psycopg 3 nativo; los otros dos los sirve
`ThreadedAsyncDriver`, que corre un driver **síncrono** sobre un hilo propio. No es fingir async: es
lo que hace `aiosqlite` por dentro, y en MySQL da concurrencia real, porque Python suelta el GIL
mientras el socket espera. Lo que no da es el rendimiento de un protocolo nativo bajo mucha carga — y
un driver nativo entraría como otra implementación del mismo Protocol, sin tocar nada encima.

**Los drivers se componen.** Además de los seis concretos, `drivers/` trae decoradores que envuelven
a otro driver y que la sesión no distingue:

| Decorador | Qué añade |
|---|---|
| `SnakePool` / `AsyncSnakePool` | Presta una CONEXIÓN por sesión, con `pre_ping`, `recycle_seconds` y timeout de préstamo |
| `LoggingDriver` / `AsyncLoggingDriver` | Registra el SQL que pasa por él, en un escritor inyectado |
| `TimeoutDriver` / `AsyncTimeoutDriver` | Fija un `statement_timeout` en la conexión: una consulta colgada agota el pool |
| `ThreadedAsyncDriver` | Sirve un driver síncrono como `AsyncDriver`, un hilo por conexión |
| `CaptureDriver` / `AsyncCaptureDriver` (`debug/`) | Graba cada sentencia en el colector del scope para el panel de depuración |

## Dónde va una funcionalidad: encima de la costura o debajo

`EXPLAIN` y los `notices` del servidor comparten fila en el roadmap y son problemas opuestos, que es
la forma más clara de leer la costura.

`EXPLAIN` vive **encima**. El compilador ya devuelve `(sql, params)` y el dialecto es dueño de la
gramática, así que la funcionalidad entera es:

```python
sql, params = query.to_sql(dialect)        # already compiled, already parametrised
rows = driver.fetch_all(dialect.explain_sql(sql), params)
```

No se mueve nada de `SnakeDriver`. Los `notices` viven **debajo**: son un canal fuera de banda de la
conexión, no una sentencia, así que no se alcanzan sin ensanchar el Protocol.

**Y ensanchar es el movimiento caro.** Todos los wrappers de `drivers/` delegan método a método —no
hay un solo `__getattr__` y varios usan `__slots__`—, así que un miembro nuevo cuesta 13 clases de
producción más los dobles de test, y `test_the_two_driver_protocols_declare_the_same_members` lo
cobra en los dos colores automáticamente. La regla que se sigue: **ensanchar UNA vez, con todo lo que
vaya a entrar**, nunca método a método.

El método de dialecto que devuelve una cadena por motor es la forma a copiar
(`statement_timeout_sql`, `explain_sql`, `json_get_sql`): la gramática cambia, la ejecución no.

## Lo que el plan NO normaliza

Dos huecos conocidos, escritos aquí porque los dos parecen descuidos y no lo son:

- **Los errores de los motores llegan en crudo.** Un `CHECK` rechazado es un `CheckViolation`, un
  `OperationalError` o un `IntegrityError` según el driver. El ORM no los traduce, así que el usuario
  escribe la misma tabla de tres que escriben los tests.
- **La forma de la respuesta de un `EXPLAIN` es la del motor.** Postgres devuelve una columna, SQLite
  cuatro y MySQL una docena, y `plan_raw` valida la anchura de forma estricta, así que una sola fila
  declarada no puede servir a los tres. Por eso `explain()` devuelve las líneas del motor en vez de
  inventar una forma sobre tres cosas que no comparten ningún campo.

## Guardas: la capa de pre-vuelo

`session/guards.py` hace cumplir un **límite declarado** en Python, antes de tocar la base:
`_guard_declared_limits` recorre las columnas y delega en `_guard_scale`, `_guard_length`,
`_guard_int_range` y `_guard_timezone`; `_guard_required_values` cubre el caso del valor que falta.

**En ese fichero viven dos guardas más que no van del valor de una columna.** Son los únicos nombres
PÚBLICOS del fichero —a los de arriba se llega por `_guard_declared_limits`, a éstos los llaman
directamente las dos sesiones, síncrona y asíncrona, que es justo el motivo de que vivan aquí en una
sola pieza—: `guard_can_set_isolation` rechaza `SET TRANSACTION ISOLATION LEVEL` sobre un motor cuyo
catálogo contesta `Nope`, y se mudó aquí porque la sesión síncrona preguntaba al catálogo mientras la
asíncrona le pasaba la sentencia al driver, con lo que SQLite contestaba `near "SET": syntax error`.
`guard_uniform_bulk_columns` rechaza un `add_all` cuyas instancias no presentan las MISMAS columnas.

Esa segunda es una negativa que el usuario se come de frente, así que va entera:

```text
SnakeEmitError: Every row of a bulk INSERT must have the same columns, and these Note instances do not: tag, title / title. One model does not mean one shape — a column with a server default stays out of the constructor, so assigning it on some instances and not others splits the batch. Either assign it on all of them or on none, or call add() per instance.
```

Un modelo no significa una forma: una columna con default de servidor se queda fuera del `__init__`,
así que dos instancias de la misma clase acaban legítimamente con conjuntos distintos de valores
asignados, y filas con columnas distintas no pueden compartir un INSERT multi-fila. Sin la guarda,
`add_all` se bifurcaba mirando la PRIMERA fila y emitía `DEFAULT VALUES` para todas las instancias
siempre que ésa saliera vacía — los valores del resto se calculaban y se tiraban, mientras que dando
la vuelta a esa misma lista el emisor la rechazaba. La POSICIÓN de un elemento decidía entre un error
ruidoso y una pérdida callada de datos.

Rechazar en vez de partir el lote en grupos es la doctrina, y además cumple una segunda promesa:
agrupar devolvería las filas en un orden que quien llama no eligió, y `add_all` garantiza que no hace
eso.

`snake_str(max_length=5)`, `snake_int(size=SMALLINT)` y `snake_decimal(precision=…, scale=…)` son
**reglas del dominio**, no adornos del DDL. Si el ORM solo las escribiera en el DDL, las haría
cumplir el MOTOR — y entonces valdrían distinto según dónde corras: Postgres rechaza (`value too
long`, `smallint out of range`) y SQLite acepta, porque ignora la longitud del VARCHAR y colapsa los
enteros. El dialecto SQLite existe para poder trabajar sin servidor, así que sin esto la suite sale
verde en desarrollo y el despliegue a Postgres revienta.

Viven **fuera** de la sesión porque no son ejecución: no hablan con el driver, no saben de
transacciones y no dependen de si alguien esperó.

Ninguna trunca ni redondea. Un `max_length` que corta la cadena convierte una regla en una pérdida de
datos silenciosa; el ORM grita y el que escribe decide.

## Riesgos — estado tras spikes

| Riesgo | Estado |
|------|--------|
| `slots=True` + descriptores por campo | ✅ modelos SIN slots; `metadata/` sí usa slots |
| Almacenamiento del valor en el descriptor | ✅ `__set_name__` + `object.__setattr__`, sin fugas |
| `SnakeToMany[M]` → `list[M]`, y acceso de clase que NIEGA las columnas del hijo | ✅ `SnakeCollection[M]`, probado en mypy y pyright |
| FK compuesta (join AND-eado, mapeo posicional) | ✅ diseño cerrado |
| `select()` heterogéneo → `tuple[...]` | ✅ probado con overloads posicionales |
| Forward-refs + circulares (compiler/linker) | ✅ probado `City↔Country` con `from __future__ import annotations` |
| Async sin duplicar la sesión | ✅ el `Plan` incoloro; las dos sesiones consumen el mismo |
| Un segundo y un tercer motor | ✅ MySQL/MariaDB y SQLite: un fichero nuevo cada uno, no un refactor |
