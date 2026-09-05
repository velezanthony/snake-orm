# Columnas y tipos

```python
from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeUtc,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_model,
    snake_str,
)

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()  # autoincrement PK (out of __init__)
    email: SnakeColumn[str] = snake_str(unique=True)
    bio: SnakeColumn[str | None] = snake_str(default=None)  # nullable by the annotation
    active: SnakeColumn[bool] = snake_column(default=True)
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)

user = User(email="a@b.com")  # keyword-only; only what has no default is required
```

**La regla: el tipo viene de Python. La metadata solo añade información de SQL.**

!!! warning "Que admita NULL no es un default"

    `str | None` dice que la columna acepta `NULL`. **No** hace que el argumento sea opcional: sin
    `default=` ni `default_factory=`, `User(email="a@b.com")` lanza
    `TypeError: User() missing required argument: 'bio'`. Son dos decisiones distintas.

## Un specifier por familia de tipo

`snake_column()` declara las columnas **sin parámetros de tipo**: `bool`, `date`, `UUID`, `bytes`,
`timedelta`, `list[T]`... Las familias que sí tienen algo que declarar traen su propio specifier.
Son **siete**, y dos de ellas se parten en dos declaradores porque la elección ES el parámetro:

```python
stock:      SnakeColumn[int]      = snake_int(size=SnakeIntSize.SMALLINT)
name:       SnakeColumn[str]      = snake_str(max_length=50)       # fixed=True -> CHAR(50)
ratio:      SnakeColumn[float]    = snake_float(size=4)
price:      SnakeColumn[Decimal]  = snake_decimal(precision=12, scale=2)
meta:       SnakeColumn[dict[str, object]] = snake_json(storage=SnakeJsonStorage.JSON)
created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(precision=3)  # or snake_datetime(precision=3)
opening:    SnakeColumn[time]     = snake_time()                   # or snake_timetz()
```

`Decimal` decide que la columna es `NUMERIC`; `precision` y `scale` deciden *cuál*. Ningún
parámetro cambia el tipo ni contradice la anotación.

Van separados porque un `max_length` en un entero no significa nada: en un único `snake_column()`, el
editor te lo autocompletaría en **todas** las columnas. Y si lo pones donde no toca, el compiler
**falla al importar**, no en el `migrate`:

```python
age: SnakeColumn[int] = snake_str(max_length=50)
# SnakeModelDefinitionError: ... declares max_length=50 with snake_str(), which only
# applies to a str column, but its type is 'int'. The ANNOTATION is what rules the type: ...
```

Un parámetro que **necesita a otro** también falla al importar, y el caso con el que te vas a topar
es `fixed=True` sin `max_length`:

```text
SnakeModelDefinitionError: A fixed-length column has to say HOW MANY characters: declare
snake_str(max_length=n, fixed=True). A CHAR without a length is CHAR(1) in SQL, and that is almost
never what anyone wants.
```

Mismo patrón que `snake_enum(...)` para los enumerados y `snake_auto()` para la PK autoincremental.

## Tipos soportados

| Python | Declarador | PostgreSQL | MySQL | SQLite |
|---|---|---|---|---|
| `int` | `snake_int()` | `BIGINT` | `BIGINT` | `INTEGER` |
| `int` (PK) | `snake_auto()` | `BIGSERIAL` | `BIGINT AUTO_INCREMENT` | `INTEGER` |
| `str` | `snake_str(max_length=50)` | `VARCHAR(50)` | `VARCHAR(50)` | `TEXT` |
| `str` (fijo) | `snake_str(max_length=2, fixed=True)` | `CHAR(2)` | `CHAR(2)` | `TEXT` |
| `bool` | `snake_column()` | `BOOLEAN` | `TINYINT(1)` | `INTEGER` |
| `float` | `snake_float()` | `DOUBLE PRECISION` | `DOUBLE` | `REAL` |
| `float` (4 bytes) | `snake_float(size=4)` | `REAL` | `FLOAT` | `REAL` |
| `Decimal` | `snake_decimal(precision=12, scale=2)` | `NUMERIC(12,2)` | `DECIMAL(12,2)` | `TEXT` |
| `SnakeUtc` | `snake_datetimetz()` | `TIMESTAMPTZ` | `TEXT` | `TEXT` |
| `datetime` | `snake_datetime()` | `TIMESTAMP` | `DATETIME(6)` | `TEXT` |
| `date` | `snake_column()` | `DATE` | `DATE` | `TEXT` |
| `time` | `snake_time()` | `TIME` | `TIME(6)` | `TEXT` |
| `time` (con zona) | `snake_timetz()` | `TIMETZ` | `TEXT` | `TEXT` |
| `timedelta` | `snake_column()` | `INTERVAL` | `TEXT` | `TEXT` |
| `UUID` | `snake_column()` | `UUID` | `CHAR(36)` | `TEXT` |
| `bytes` | `snake_column()` | `BYTEA` | `LONGBLOB` | `BLOB` |
| `dict` | `snake_json()` | `JSONB` | `JSON` | `TEXT` |
| `list[int]` | `snake_column()` | `BIGINT[]` | `TEXT` | `TEXT` |

### Cuatro ayudantes, y por qué no son `datetime.now()`

```python
from snakeorm import utc_now, parse_utc, to_utc, utc_from_zone
from datetime import datetime

utc_now()                                          # now, zoned, in UTC
parse_utc("2026-01-01T12:00:00+01:00")             # ISO with a zone -> the instant in UTC
utc_from_zone(datetime(2026, 1, 1, 12, 0), "Europe/Madrid")   # a wall clock -> the instant
to_utc(already_zoned)                              # re-expresses; it does not move the instant
```

`SnakeUtc` es un INSTANTE: entra con zona y vuelve con zona. Un `datetime.now()` ingenuo no tiene
zona, así que el instante que nombra depende de la máquina que lo produjo — por eso existen éstos y
no la llamada más corta de la biblioteca estándar. `utc_from_zone` es el que hace falta cuando lo que
tienes es una hora de pared que alguien leyó de un formulario.

Cada tipo tiene un test de ida y vuelta en los tres motores
(`src/test/integration/test_type_round_trip.py`): escribe un valor y exige que vuelva con su valor **y su
tipo**.

Dos casillas de esa tabla merecen una línea:

- En **MySQL** un `snake_datetimetz()` cae a `TEXT` en ISO-8601, que conserva el instante entero,
  huso incluido — más de lo que conservaría un `DATETIME`. El tipo con zona propio de MySQL
  (`TIMESTAMP`) topa en 2038.
- En **SQLite** un `Decimal` se guarda como `TEXT`: la afinidad `NUMERIC` lo convertiría a `REAL` y
  perderías la exactitud.

!!! danger "En MySQL un `Decimal` DEBE declarar su precisión"

    Postgres mapea un `Decimal` pelado a un `NUMERIC` sin límite y no pierde nada, así que el modelo
    parece correcto ahí. MySQL no tiene decimal sin límite: un `DECIMAL` pelado es `DECIMAL(10,0)`, y
    **9.99 se guarda como 10**.

    ```python
    price: SnakeColumn[Decimal] = snake_column()                          # refused on MySQL
    price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)    # portable
    ```

    Por eso el dialecto para el plan en vez de elegir una precisión que nadie declaró. Y ojo: esto no
    es algo que `Degraded` pudiera cubrir — lo que se pierde no es una capacidad de consulta, es el
    VALOR.

!!! note "Lo que un motor no tiene cae a TEXT, y el VALOR vuelve EXACTO"

    Es la regla que hay detrás de cada `TEXT` de la tabla de arriba: un tipo para el que el motor no
    tiene equivalente **no se rechaza**. Cae a `TEXT` y funciona — el valor entra y sale exacto. Lo
    que se degrada es la **semántica SQL**: ordenar, comparar, operar con él. Una `list[T]` es el
    caso más claro: ni MySQL ni SQLite tienen arrays, así que en los dos se guarda como JSON en una
    columna `TEXT` y vuelve siendo la misma lista; lo que no se puede es consultar **dentro** de ella.

    Cada salvedad es una capacidad **declarada**, así que se puede preguntar en vez de suponer:
    `session.dialect.supports_returning` es pública. Al abrirla, además, la sesión avisa **una vez
    por salvedad**, y solo de las que tus modelos usan de verdad.

## Claves primarias

`snake_auto()` es el caso autoincremental. Cualquier otra PK es `primary_key=True` en el specifier de
su familia, y está disponible en todos ellos:

```python
from uuid import UUID, uuid4

@snake_model(table="countries")
class Country(SnakeModel):                                       # NATURAL key
    code: SnakeColumn[str] = snake_str(max_length=2, fixed=True, primary_key=True)
    name: SnakeColumn[str] = snake_str()

@snake_model(table="invoices")
class Invoice(SnakeModel):                                       # UUID key, generated in Python
    id: SnakeColumn[UUID] = snake_column(primary_key=True, default_factory=uuid4)
    total: SnakeColumn[int] = snake_int()

@snake_model(table="order_lines")
class OrderLine(SnakeModel):                                     # COMPOSITE key
    order_id: SnakeColumn[int] = snake_int(primary_key=True)
    line_no:  SnakeColumn[int] = snake_int(primary_key=True)
    qty:      SnakeColumn[int] = snake_int()
```

La compuesta es solo `primary_key=True` dos veces: la simple y la compuesta comparten la misma
estructura interna, así que nada de lo que viene después (diff, migraciones, joins) tiene un caso
especial para ninguna de las dos. Para un UUID que genere el servidor en vez de Python, usa
`server_default=SnakeServerDefault.UUID_V4`.

## Un tipo que el ORM no trae

El vocabulario de tipos es **abierto**: si necesitas un `INET`, un `CITEXT`, un `TSVECTOR` o un tipo
propio de tu dominio, lo registras en el dialecto y a partir de ahí se declara como cualquier otro.

Son **dos ejes**, y hay que declarar los dos: cómo se ESCRIBE la columna y cómo VIAJA el valor.

```python
from snakeorm import (
    PostgresDialect, SnakeColumn, SnakeModel, SQLiteDialect,
    register_converter, snake_auto, snake_column, snake_model,
)

class Inet:
    """An IP address in your domain."""

    def __init__(self, value: str) -> None:
        self.value = value

# Axis 1 — how it is WRITTEN. Per DIALECT: each engine writes the same Python type differently.
PostgresDialect().register_type(Inet, "INET")
SQLiteDialect().register_type(Inet, "TEXT")

# Axis 2 — how the value TRAVELS. Global, and `from_db` has to be IDEMPOTENT.
register_converter(
    Inet,
    to_db=lambda ip: ip.value,
    from_db=lambda raw: raw if isinstance(raw, Inet) else Inet(str(raw)),
)

@snake_model(table="servers")
class Server(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    address: SnakeColumn[Inet] = snake_column()
```

El primer eje va **por dialecto** porque el mismo tipo Python se escribe distinto en cada motor:
`Inet` es `INET` en Postgres y `TEXT` en SQLite, y el modelo no se entera de ninguna de las dos
cosas. Global, importar una librería que registra un tipo se lo colaría a todos los dialectos del
proceso.

El segundo sí es **global**, con una condición: `from_db` tiene que ser **idempotente**. Ése es el
`if isinstance` del ejemplo, y es lo que permite que un solo conversor lea de los tres motores,
porque cada uno devuelve la columna en una forma distinta: Postgres con un `INET` nativo puede
entregarte ya el objeto y SQLite te da el texto. Se comprueba al registrar, no en la primera lectura
de producción. Si te saltas este eje, el tipo llega al driver como un objeto que no sabe enviar.

La resolución va por **MRO**, así que un `class IPv4(Inet)` hereda el viaje — y en el otro sentido,
si tu tipo hereda de uno que el ORM ya trata (`class Slug(str)`), escribir funcionaría y **la lectura
te devolvería un `str`**.

Lo que `register_converter` **no** hace es reescribir un tipo que el ORM ya trata — `Decimal`,
`UUID`, `datetime` y compañía lanzan `SnakeConfigError`:

```text
SnakeConfigError: <class 'decimal.Decimal'> is a type the ORM already handles, so its converter is
not rewritten. A global registry is shared by the whole process: changing here how a core type
travels would change it too for code that asked for nothing.
```

El eje del dialecto no tiene ese problema —va por instancia— y por eso ahí sí se puede reescribir un
tipo nativo: `register_type(str, "CITEXT")` deja toda la base insensible a mayúsculas.

Sin registrar, un tipo desconocido **sigue fallando**. Adivinar el tipo SQL de una clase cualquiera
sería peor que negarse; lo que hace el error es decirte cómo registrarlo.

## Un límite declarado se cumple en Python, no lo delega al motor

```python
code:     SnakeColumn[str]     = snake_str(max_length=5)
quantity: SnakeColumn[int]     = snake_int(size=SnakeIntSize.SMALLINT)
amount:   SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
```

Son reglas de tu dominio, y el ORM las hace cumplir **al escribir**, antes de tocar la base — con
una excepción que se nombra más abajo:

```python
session.add(Product(code="TOO LONG TO FIT"))
# SnakeValueError: ... declares max_length=5 but an attempt was made to write a text of
#                  15 characters. Trim it yourself before saving it: the ORM does not
#                  truncate in silence.
```

Es lo que hace que **tu modelo signifique lo mismo en los tres motores**. Postgres rechazaría los
dos primeros (`value too long`, `smallint out of range`); SQLite los aceptaría, porque ignora la
longitud del VARCHAR y colapsa todos los enteros a 64 bits. Sin la comprobación, desarrollar en
SQLite y desplegar a Postgres sería una trampa.

!!! warning "`precision` NO es uno de ellos"

    El guardia cubre `max_length`, `int_size` y `scale`. **No** comprueba `precision`: un `Decimal`
    más ancho que los dígitos que declaraste pasa, y lo que ocurra después lo decide el motor —
    SQLite lo guarda, Postgres lanza `numeric field overflow`. O sea que ese botón concreto no se
    comporta igual en los tres, que es justo lo contrario de lo que compra el resto de esta sección.
    Hasta que lo haga, trata una `precision` declarada como documentación para el DDL y no como una
    regla que el ORM sostenga.

Se **grita**, nunca se recorta. Vale para `add`, `add_all`, `upsert`, `update` y también para la
escritura masiva `update_where`.

### Y una columna obligatoria sin valor también grita

Una guarda hermana salta con el problema contrario: una columna que llega **sin valor ninguno**.
Omitir una del `INSERT` es lo correcto casi siempre —una PK autoincremental, una columna con default,
una que rellena el servidor—, así que la guarda separa el único caso en el que no lo es: `NOT NULL`,
sin default de ningún tipo (`default=`, `default_factory=`, `server_default=`) y sin autoincremento.
Ahí, que falte el valor no significa "que lo ponga la base", significa que no lo puso nadie.

```text
SnakeValueError: 'lines.order_id' is mandatory (NOT NULL, without a default and without
autoincrement) and an attempt was made to write it without a value. It usually means the value comes
from another row whose id never came back: on an engine without RETURNING, `add_all()` does not fill
in autoincrementing keys, so use `add()` for the rows whose id you need afterwards.
```

## Fechas: instante u hora de pared, y lo dice el TIPO

```python
from datetime import datetime
from snakeorm import SnakeColumn, SnakeUtc, snake_datetime

created_at: SnakeColumn[SnakeUtc] = snake_datetimetz()  # an INSTANT    -> TIMESTAMPTZ
opening:    SnakeColumn[datetime] = snake_datetime()    # a WALL TIME   -> TIMESTAMP
```

`SnakeUtc` es un instante en UTC, y **no se puede construir uno que no lo sea**. Un `datetime` a
secas es una hora de pared —un horario de apertura, un festivo local— que no identifica ningún
momento hasta que alguien dice de qué zona es. Una guarda exige que la anotación case con el
declarador, y un `snake_column()` sobre una fecha es un error, porque no dice cuál de los dos
quieres.

No hay perilla `tz=`, y es a propósito: si la hubiera, el tipo y el declarador dirían los dos lo
mismo y podrían contradecirse. Dos fuentes de verdad, una puede mentir — la razón exacta por la que
no existe `nullable=`.

### De dónde vienen las fechas, y cómo entran

```python
from snakeorm import SnakeUtc

# 1. JS: date.toISOString() -> "2026-06-01T12:30:00.000Z". Already in UTC.
when = SnakeUtc.parse(payload["when"])

# 2. A form: <input type="datetime-local"> -> "2026-06-01T14:30". NO zone.
#    Only YOU know which zone that time is in, so you are the one who supplies it.
when = SnakeUtc.from_zone(datetime.fromisoformat(form["when"]), user.zone)

# 3. Right now
when = SnakeUtc.now()

# 4. A datetime you already have, with a zone
when = SnakeUtc.of(other_aware)
```

### Y de vuelta, para pintarla

```python
appointment.when                              # SnakeUtc: 2026-06-01 12:30:00+00:00
appointment.when.to_zone("Europe/Madrid")     # datetime: 2026-06-01 14:30:00+02:00
```

Se guarda en UTC y se muestra en la zona de quien lee. Convertida a Madrid ya **no** es un
`SnakeUtc` —porque ya no está en UTC—, y por eso el tipo cambia a `datetime`.

!!! tip "Es un `datetime` para todo lo de fuera"

    `SnakeUtc` hereda de `datetime`, así que `isinstance`, `isoformat()`, `strftime()`, DRF,
    Pydantic, Jinja y `json` funcionan sin enterarse de que existe. Lo que el checker impide es lo
    contrario: meter un `datetime` cualquiera donde se pide un instante.

!!! warning "Un `<input type=\"datetime-local\">` no se puede resolver solo"

    `"2026-06-01T14:30"` no dice de dónde es esa hora, así que `SnakeUtc.parse()` lo **rechaza**.
    O mandas la zona (un campo oculto con `Intl.DateTimeFormat().resolvedOptions().timeZone`), o la
    sacas del perfil del usuario, o conviertes en JS antes de enviar. Lo que el ORM no va a hacer
    es suponerla.

!!! tip "Para verlo con `+00` también desde `psql`"

    `TIMESTAMPTZ` guarda el instante, pero lo **muestra** en la zona de la sesión. Las conexiones
    que abre el ORM ya piden UTC (viaja en el DSN, sin ejecutar ninguna sentencia), así que todo lo
    que pase por él ve `+00`. La sesión de un `psql` ajeno usa la zona del servidor; si quieres que
    el vistazo diga la verdad para todo el mundo, fíjalo en la base:

    ```sql
    ALTER DATABASE my_database SET timezone = 'UTC';
    ```

## Nulabilidad

```python
nickname: SnakeColumn[str | None] = snake_str()  # NULL allowed
email:    SnakeColumn[str]        = snake_str()  # NOT NULL
```

No existe `nullable=`. Lo decide la anotación.

## Defaults: hay tres, y son distintos

```python
from snakeorm import SnakeServerDefault

active:     SnakeColumn[bool]     = snake_column(default=True)
created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)
stamped:    SnakeColumn[SnakeUtc] = snake_datetimetz(server_default=SnakeServerDefault.NOW)
```

| | Quién lo calcula | Dónde acaba |
|---|---|---|
| `default=` | Nadie: es un literal | En el `DEFAULT` del DDL **y** en el objeto |
| `default_factory=` | Python, al construir | Solo en el objeto (valor fresco por instancia) |
| `server_default=` | El servidor, al insertar | En el DDL; excluye la columna del `__init__` |

Declarar dos a la vez es un error al definir el modelo. `SnakeServerDefault` es agnóstico del motor y
tiene cinco miembros (`NOW`, `UUID_V4`, `TRUE`, `FALSE`, `ZERO`); el dialecto lo traduce. Para SQL
crudo hay `server_default_sql=` (ya no portable).

## Unicidad

```python
email: SnakeColumn[str] = snake_str(unique=True)
```

Emite una **constraint** `uq_users_email`, no un índice. La constraint DICE la regla; es lo que
referencian `ON CONFLICT` y los mensajes de error. La única excepción es el único **parcial** (sale
un índice, porque PostgreSQL no admite `UNIQUE ... WHERE`). Ver
[índices y constraints](indexes-and-constraints.es.md).

## Enumerados

```python
from enum import StrEnum
from snakeorm import snake_enum

class Status(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    status: SnakeColumn[Status] = snake_enum(Status, default=Status.ACTIVE)
```

Por defecto se guarda como una cadena con un `CHECK IN (...)` derivado de los miembros: añadir un
valor cambia el CHECK y el diff genera la migración. El ANCHO también se deriva —el miembro más
largo—, así que la columna es `VARCHAR(n)` donde el motor tiene longitudes y `TEXT` en SQLite, que no
las tiene. Nadie declara ese ancho: el ORM ya lo sabe por el enum. El viaje de vuelta devuelve el
**miembro**:

```python
user.status is Status.ACTIVE  # True
```

`storage=` elige qué objeto de la base hace la comprobación, y hay dos:

```python
from snakeorm import SnakeEnumStorage

status: SnakeColumn[Status] = snake_enum(Status, storage=SnakeEnumStorage.PLAIN)
```

| | Qué sale | Coste |
|---|---|---|
| `CHECK` (defecto) | tipo base + `CHECK col IN (...)` | quitar un miembro falla en `migrate` si hay filas usándolo |
| `PLAIN` | solo el tipo base, sin validación | un valor malo colado por SQL crudo revienta **al leer** |

No hay `NATIVE`, y es a propósito. En Postgres `ADD VALUE` no tiene inversa (recrear el tipo reescribe
la tabla bajo `ACCESS EXCLUSIVE`), el valor no se puede usar en la misma transacción que lo añade —y
las migraciones son transaccionales— y dos modelos que compartan el enum comparten el tipo. Con
`CHECK` no pasa nada de eso.

!!! warning "Anotar un Enum sin `snake_enum()` es un error al declarar"

    Un solo camino, explícito. Sin él, el valor volvería como `str` crudo: el tipo prometido sería
    mentira. El `default=` es un **miembro**, no un string (`default="active"` no compila).

## Nombre de columna distinto al del atributo

```python
created: SnakeColumn[SnakeUtc] = snake_datetimetz(name="created_at")
```

El atributo es `created`; la columna, `created_at`. Útil sobre todo con
[DB-first](../engines/db-first.es.md), donde el nombre SQL ya existe.

## Comentarios

```python
email: SnakeColumn[str] = snake_str(db_comment="Login key; unique")
```

Emite `COMMENT ON COLUMN`, entra en el diff y viaja en las migraciones. También hay
`SnakeComment = "..."` a nivel de clase para la tabla.

---

Siguiente: [relaciones](relationships.es.md).
