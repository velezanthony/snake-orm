# PostgreSQL, MySQL y SQLite

```python
from snakeorm import (
    MySQLDialect, PostgresDialect, PsycopgDriver, PyMySQLDriver,
    SQLiteDialect, SQLiteDriver, SnakeSession,
)

pg     = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
mysql  = SnakeSession(PyMySQLDriver.connect(host="...", database="..."), MySQLDialect())
sqlite = SnakeSession(SQLiteDriver.connect("./my.db"), SQLiteDialect())
```

Mismo modelo, mismo query. Solo cambian **driver** y **dialecto**. Y ni eso hace falta elegirlo a
mano: `SnakeConnectionConfig(backend=...)` los empareja, para que nadie pueda juntar el driver de un
motor con el dialecto de otro. Cada driver, dialecto y config de ese bloque está en
[Motores](../reference/api/engines.es.md).

## Los tres ejes

| Eje | Qué decide | Protocolo |
|---|---|---|
| **Dialecto** | Cómo se ESCRIBE el SQL | `SnakeDialect` |
| **Driver** | Cómo se EJECUTA | `SnakeDriver` |
| **Introspector** | Cómo se LEE el esquema | `SnakeIntrospector` |

Separarlos es lo que hace que añadir un motor sea **un fichero nuevo, no un refactor**.

## La regla de oro

**Los modelos y el grafo de metadata son 100% agnósticos del motor.** El dialecto solo entra al
emitir y ejecutar SQL. Por eso `SnakeFkAction`, `SnakeServerDefault` y `SnakeIndexMethod` son enums
agnósticos que el dialecto traduce, no strings de PostgreSQL escritos en el modelo.

## Qué cambia entre los tres

| Capacidad | PostgreSQL | MySQL / MariaDB | SQLite |
|---|---|---|---|
| Esquemas con nombre | Sí | **No** — un schema ES una base | **No** — son bases adjuntas |
| `ALTER TABLE ADD CONSTRAINT` | Sí | Sí | **No** |
| `ALTER COLUMN` | Sí | Sí (`MODIFY COLUMN`) | **No** |
| DDL transaccional | Sí | **No** — commit implícito | Sí |
| `SELECT ... FOR UPDATE` | Sí | Sí | No |
| Comentarios de tabla y columna | Sí (`COMMENT ON`) | Sí, como CLÁUSULA (`... COMMENT = '...'`) | **No** — no guarda ninguno |
| `RETURNING` | Sí | **No** — el PK va por `lastrowid` | Sí |
| `ILIKE` | Sí, el operador | Se escribe `LOWER()`; pliega lo que pliegue la collation | Se escribe `LOWER()`; pliega solo ASCII |

!!! danger "Un dialecto que olvida una capacidad no llega a importarse"

    A `Cap` se le contesta ENTERO o el dialecto lanza `SnakeDialectError` al construirse, nombrando
    cada capacidad que se dejó. No hay valor por defecto: una sin declarar se leería como no
    soportada sin que nadie lo haya decidido, que es un silencio por omisión en el ORM que grita.

El ORM lee esas capacidades del dialecto. **Nunca las ignora en silencio**: o traduce a un
equivalente exacto, o para y lo dice.

### Y lo que se hace A MEDIAS también se declara

Hay una tercera respuesta además de "sí" y "no", y es la que más se nota en el día a día: el motor
lo hace, pero mintiendo en algo. Un `Decimal` en SQLite se guarda como TEXT — vuelve **exacto**, y
ordena como texto, así que `'9.99'` sale después de `'10.00'`. Un `SnakeUtc` en MySQL conserva el
instante entero, y el motor no lo trata como fecha al comparar.

De todo eso te avisa la sesión **al abrirla, una vez por cosa**, y solo de lo que tus modelos usan
de verdad. Si tienes controlado alguno:

```python
import warnings
from snakeorm import SnakeWarning

warnings.filterwarnings("ignore", category=SnakeWarning)
```

### Un tipo que el motor no tiene

No se rechaza: cae a `TEXT` y **funciona**. El valor entra y sale exacto —el texto no pierde nada—
y lo que se degrada es la semántica SQL. Así el mismo modelo corre en los tres motores, y lo que
cada uno se deja por el camino está dicho en voz alta en vez de descubrirse en producción.

### DDL no transaccional en MySQL

MySQL hace commit implícito en cada sentencia de DDL, así que **una migración de N pasos no es
todo-o-nada**: si el paso 3 falla, los dos primeros ya están aplicados. El ORM no puede arreglarlo
—no es cosa suya—, pero sí para en el PLAN todo lo que sabe que ese motor no puede hacer, para que
el fallo no llegue a mitad del despliegue.

## El catálogo de capacidades

Todo lo de arriba sale de un único sitio: `Cap`, el enum que lista todo lo que cualquier motor podría
hacer. Cada dialecto declara un `SnakeCapabilities` que contesta al catálogo **entero**, miembro a
miembro, con uno de tres valores.

Cuántos miembros tiene hoy no está escrito aquí a propósito: el catálogo crece, y un número copiado
en la prosa es una copia que nadie actualiza. La orden que lo contesta:

```bash
uv run python -c "from snakeorm.dialects.capabilities import Cap; print(len(list(Cap)))"
```

```python
from snakeorm.dialects.capabilities import Cap, Degraded, Full, Nope, SnakeCapabilities

capabilities = SnakeCapabilities(
    {
        Cap.RETURNING: Full(),                       # does it, and does it right
        Cap.UPSERT: Nope("no ON CONFLICT in this engine"),
        Cap.DECIMAL_ORDERING: Degraded("stored as TEXT: sorts lexicographically"),
        # ... and the rest of the catalogue, every last member of it
    }
)
```

`Degraded` y `Nope` **exigen un motivo**, y no es un comentario: es el texto exacto que el usuario
lee al abrir la sesión o cuando el plan se para. Sin él, el mensaje diría que algo no se puede y te
dejaría igual de perdido.

!!! danger "Un dialecto al que se le olvide una capacidad no se puede ni importar"

    `SnakeCapabilities.__post_init__` comprueba que están contestadas TODAS y lanza
    `SnakeDialectError` nombrando las que faltan — quien cuenta es `Cap`, así que aquí no hay ningún
    número que mantener al día. Como el dialecto construye su catálogo en un
    atributo de clase, esa comprobación salta **al importar el módulo** — no hay forma de meter un
    dialecto declarado a medias en un proceso vivo.

    ```text
    SnakeDialectError: This dialect does not answer 2 capability(ies) of the catalogue: UPSERT,
    ILIKE. Every engine declares them ALL: an undeclared capability would read as
    unsupported without anyone having decided so.
    ```

    Ésa es la diferencia deliberada con un `frozenset` de capacidades soportadas, que sería más
    corto de escribir: en un conjunto, la capacidad que se te olvidó no está, y "no está" se lee como
    "no soportada" — un default silencioso, en el ORM que grita. Así que añadir un motor son tres
    ficheros y no cambia nada del núcleo, pero esos tres ficheros tienen que contestar a todo.

### Qué PARA el plan y qué solo AVISA

El catálogo se parte en dos `frozenset`, y la diferencia es lo que te pasa a ti:

| Conjunto | Cuántas | Qué hace |
|---|---|---|
| `PLAN_CAPS` | `len(PLAN_CAPS)` | Alguien **la lee para decidir**: para una operación o cambia la forma del SQL emitido. |
| `ADVISORY_CAPS` | `len(ADVISORY_CAPS)` | Nada del plan depende de ellas. Se declaran **para avisar**. |

La columna es la expresión y no un número por lo mismo que arriba: `ADVISORY_CAPS` es literalmente
`frozenset(Cap) - PLAN_CAPS`, así que los dos tamaños se mueven el día que se añade un miembro.

En `PLAN_CAPS` están las ESTRUCTURALES — el tipo de pregunta cuya respuesta cambia el SQL o para la
operación, en vez de matizar un aviso. `RETURNING` y bloquear una fila son de ese tipo; el carácter
con el que un dialecto entrecomilla un identificador no lo es.

La lista no se escribe aquí, y es la misma decisión que no escribir el tamaño de arriba: una lista de
miembros copiada en la prosa se pudre igual que un número, en silencio — y ésta se había podrido ya,
cuando alguien fue a comprobarlo. El conjunto se contesta solo:

```bash
uv run python -c "from snakeorm.dialects.capabilities import PLAN_CAPS; print(sorted(c.name for c in PLAN_CAPS))"
```

Las dos que la gente se encuentra de verdad son `PARTIAL_INDEXES` y `DROP_COLUMN_CASCADES_FK`: un
índice `UNIQUE` parcial para en MySQL, y un `DROP COLUMN` sobre una columna que aún sujeta una clave
ajena para en MySQL y en SQLite.

`ADVISORY_CAPS` es el resto: las nueve de fidelidad de tipo (`DECIMAL_ORDERING`, `TIMESTAMPTZ`,
`INTERVAL`, `JSON`, `UUID`, `BOOLEAN`, `INT_WIDTHS`, `ARRAYS`, `FLOAT_SPECIALS`) más **tres que no van
de tipos en absoluto**:

- `INDEX_METHODS`, que la hace cumplir el propio `index_method()` del dialecto — rechaza el método
  que no conoce en vez de emitir un índice normal y mentir.
- `ILIKE`, que se mudó aquí desde `PLAN_CAPS` y es el motivo de que `Nope` significara dos cosas.
  Los tres motores buscan sin distinguir mayúsculas —uno tiene el operador y a los otros dos el
  emisor les escribe `LOWER(a) LIKE LOWER(b)`—, así que no se rechaza nada y ningún plan se para.
  Qué FORMA escribir lo dice `syntax.has_ilike`; lo que dice esto es cuánto pliega, que es un
  `Degraded`.
- `CALENDAR_INTERVAL`: sumarle MESES o AÑOS a una fecha, la única parte de la aritmética de fechas
  que un calendario tiene que interpretar. `2026-01-31` más un mes es `2026-02-28` en PostgreSQL y
  MySQL, que recortan, y `2026-03-03` en SQLite, que desborda. No se rechaza nada —la fecha se
  calcula y vuelve—, así que avisa en vez de parar. Días, horas, minutos y segundos son un lapso fijo
  y los tres motores coinciden exactamente.

### Cómo funciona de verdad el aviso al arrancar

`SnakeSession(...)` y `AsyncSession(...)` llaman las dos al mismo `warn_reduced_fidelity()` —el de
`session/shared.py`, que es por lo que solo hay uno— en su constructor — **las dos sesiones emiten los mismos avisos**, del mismo catálogo y con el mismo texto.

- **Un aviso por salvedad, no uno concatenado.** Así puedes localizar el que te afecta, y silenciar
  el que ya tienes controlado no te silencia los otros seis.
- **La dedup es por `(motor, capacidad)`**, en un conjunto que lleva el propio ORM — no por el TEXTO
  del mensaje, así que retocar una coma en un motivo no vuelve a avisar de todo.
- **El filtro es una tabla de nueve capacidades, y no es la misma línea que `PLAN_CAPS`.**
  `Cap.DECIMAL_ORDERING` solo avisa si algún modelo registrado tiene una columna `Decimal`;
  `Cap.ARRAYS`, solo si hay una `list`. Contarle a alguien lo que le pasa a un `Decimal` cuando no
  tiene ninguno es ruido, y el ruido acaba en un `filterwarnings("ignore")` para toda la categoría.
- **Los genéricos se reducen a su base**: una columna `list[str]` cuenta como `list`. La salvedad es
  del contenedor (el motor no tiene arrays), no del tipo de dentro.
- **De todo lo que queda fuera de esa tabla se avisa digan lo que digan tus modelos.** Todas las de
  `PLAN_CAPS`, porque que vayas a llamar a `upsert()` o a `for_update()` no se puede saber
  leyéndolos — y también las dos advisory que no van de tipos. `INDEX_METHODS` y `CALENDAR_INTERVAL`
  no tienen tipo de Python por el que filtrar: a cualquier columna de fecha se le puede sumar un mes,
  así que en SQLite, el único motor que no contesta `Full()` a `CALENDAR_INTERVAL`, su salvedad sale
  en todas las sesiones.

| Capacidad | Avisa solo si un modelo declara |
|---|---|
| `DECIMAL_ORDERING` | `Decimal` |
| `TIMESTAMPTZ` | `SnakeUtc` |
| `INTERVAL` | `timedelta` |
| `JSON` | `dict` |
| `UUID` | `UUID` |
| `BOOLEAN` | `bool` |
| `INT_WIDTHS` | `int` |
| `ARRAYS` | `list` |
| `FLOAT_SPECIALS` | `float` |

Esa tabla es el filtro ENTERO. Una capacidad que no sea una fila suya no se filtra en absoluto.

PostgreSQL contesta `Full()` a todo el catálogo, así que su `caveats()` está vacío y abrir una sesión
contra él no dice absolutamente nada. Eso no es una plantilla: es la vara con la que se miden los
otros dos.

### La gramática no es capacidad: `SnakeSyntax`

La FORMA de una sentencia no es una capacidad. Los tres motores borran índices; lo que cambia es cómo
se escribe, y meter eso entre las capacidades fue lo que dejó `emit_alter_column` cableado a la forma
de Postgres. Las diferencias que son pura gramática viven en `SnakeSyntax`, se **traducen** en el
emisor y nunca paran el plan:

| Campo | PostgreSQL | MySQL | SQLite |
|---|---|---|---|
| `triggers_are_table_scoped` | `DROP TRIGGER x ON t` | `DROP TRIGGER x` | `DROP TRIGGER x` (global) |
| `indexes_are_table_scoped` | `DROP INDEX x` | `DROP INDEX x ON t` | `DROP INDEX x` |
| `alter_column_style` | `POSTGRES_TYPE_USING` | `MYSQL_MODIFY` | `UNSUPPORTED` |
| `empty_insert_style` | `DEFAULT_VALUES` | `EMPTY_ROW` | `DEFAULT_VALUES` |

Uno de ésos parece académico y no lo es: **`empty_insert_style`** es cómo se escribe un INSERT sin
valores, o sea una fila que es toda defaults. Lo dispara cualquier tabla puente o de eventos cuyo
único campo propio sea el id autoincremental. `INSERT INTO t DEFAULT VALUES` es el estándar y MySQL
no lo tiene; necesita `INSERT INTO t () VALUES ()`.

`alter_column_style` es un enum de tres (`AlterColumnStyle`) y no un booleano porque no hay "la"
forma: Postgres escribe `ALTER COLUMN c TYPE t USING c::t` con el `SET`/`DROP NOT NULL` en sentencias
aparte, MySQL reescribe la definición entera con `MODIFY COLUMN c t NOT NULL`, y SQLite no sabe
hacerlo sin reconstruir la tabla — así que el plan para antes de emitir nada.

Hay una tercera pieza, `SnakeLimits`, con los topes **numéricos** del motor: parámetros por sentencia
(65535 en Postgres y MySQL, 32766 en SQLite), precisión y escala de un `NUMERIC` y los dígitos de
segundo fraccionario de una fecha. Ahí `None` no significa "sin tope": significa que el motor ignora
el parámetro declarado, que es la respuesta de SQLite — tiene una afinidad por columna y nada más.

El tope de marcadores es por donde el ORM **trocea solo**, en dos sitios: `add_all()` parte el INSERT
masivo e `include()` parte el select-in. Un prefetch sobre 100.000 padres emite varias sentencias en
vez de una que el driver rechazaría.

### FK en SQLite

SQLite no admite `ALTER TABLE ... ADD CONSTRAINT`. Las FK van **dentro del `CREATE TABLE`**:

```sql
CREATE TABLE "orders" (
  "id" INTEGER, "customer_id" INTEGER NOT NULL,
  PRIMARY KEY ("id"),
  CONSTRAINT "fk_orders_customer" FOREIGN KEY ("customer_id") REFERENCES "customers" ("id")
)
```

Añadir una FK a una tabla que ya existía exigiría reconstruirla entera: el ORM **para y lo dice**.

!!! info "El driver activa `PRAGMA foreign_keys = ON` al conectar"

    SQLite ignora las FK por defecto. Un ORM que las emite pero no las verifica es el fallo
    silencioso que este proyecto persigue.

### Las tres formas de nombrar una base SQLite

Una ruta, `:memory:` o una URI `file:` — y la URI es la que compra algo que las otras dos no pueden:
una base en memoria que COMPARTEN varias conexiones, que es lo que quiere un pool o una suite de
tests.

```python
SQLiteDriver.connect("./my.db")                                  # a file
SQLiteDriver.connect(":memory:")                                 # private to this connection
SQLiteDriver.connect("file:cache?mode=memory&cache=shared")      # in memory, SHARED
```

`SQLiteDriver.connect` recibe un NOMBRE, no un DSN: si le llega un esquema `sqlite:`, revienta. Un
DSN se traduce en UN SOLO sitio, y ese sitio te devuelve el nombre:

```python
config = SnakeConnectionConfig.from_dsn(
    "sqlite:///file:cache?mode=memory&cache=shared", SnakeBackend.SQLITE
)
driver, dialect = config.driver_and_dialect()
```

!!! warning "Cuántas barras lleva una ruta absoluta"

    La tercera barra es el SEPARADOR de la URL y no parte de la ruta, así que
    `sqlite:///var/data/app.db` nombra la ruta RELATIVA `var/data/app.db`, y una absoluta lleva
    cuatro: `sqlite:////var/data/app.db`. Es la regla que documenta SQLAlchemy, y premia lo obvio:
    pegar una ruta absoluta en `f"sqlite:///{path}"` produce las cuatro por simple concatenación.

    Una ruta relativa SIGUE siendo relativa. SQLite la resuelve contra el directorio de trabajo, y
    decidir otra cosa sería este ORM adivinando lo que quisiste decir.

Solo se lee como URI una cadena que empiece por `file:`; cualquier otra cosa es un nombre de fichero
literal, interrogaciones incluidas. Así que `weird?name.db` es ese fichero y no una URI mal formada.

!!! warning "Una URI `file:` mal formada revienta, y no siempre fue así"

    Hasta que el driver pasó `uri=True`, `file:cache?mode=memory&cache=shared` se tomaba como NOMBRE
    DE FICHERO: SQLite creaba un fichero llamado exactamente así, ampersands incluidos, y seguía
    como si nada. Nunca fallaba — abría una base de datos de verdad, solo que no la que se pedía. Uno
    de esos ficheros llegó hasta un commit de este repositorio. Ahora una URI `file:` que el motor no
    sepa interpretar para en seco.

### Traducción vs. rechazo

- **Se traduce** (hay equivalente exacto): `UNIQUE` → `CREATE UNIQUE INDEX`; `DROP TRIGGER` sin el
  `ON tabla`; `CREATE OR REPLACE VIEW` → `DROP` + `CREATE`.
- **Se descarta** (no hay equivalente, y no toca los datos): los comentarios en SQLite. El
  `db_comment` no se emite; la columna se crea igual. Esta entrada nombraba también a MySQL, y era
  falso: ese motor guarda comentarios, solo que los deletrea como cláusula. Deletrear la misma
  intención distinto en cada motor es literalmente el trabajo de un dialecto, así que ahora es una
  traducción — mira la fila de arriba.
- **Se para en el PLAN** (no hay equivalente): `ALTER COLUMN`, `CREATE SCHEMA`, CHECK sobre tabla
  existente, funciones almacenadas. `realize()` corta con el motivo y la alternativa:

```text
SnakeMigrationError: The operation AlterColumn cannot be applied: this engine does not
know how to alter an existing column. On SQLite the table has to be rebuilt (create
the new one, copy the rows, drop the old one and rename), and this is the one case
the ORM does NOT do for you: `RebuildTable` only carries constraints and refuses a
pair that disagrees about a column, so do it with an explicit `RunSQL`.
```

## Añadir un motor

Tres ficheros: un dialecto (`SnakeDialect`), un driver (`SnakeDriver`) y —si quieres scaffolding— un
introspector. Nada del núcleo cambia, pero el dialecto le debe al catálogo tres respuestas completas:
su `SnakeCapabilities` (el catálogo entero), su `SnakeSyntax` y sus `SnakeLimits`. Si te dejas una, el
módulo no se puede ni importar, que es justo la idea.

---

Siguiente: [asíncrono](async.es.md).
