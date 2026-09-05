# Asíncrono

```bash
uv sync --extra async     # psycopg 3, for PostgreSQL
uv sync --extra mysql     # PyMySQL, for MySQL / MariaDB
# SQLite needs nothing extra: sqlite3 ships with the standard library
```

## La vía recomendada: que lo monte el config

```python
from snakeorm import SnakeBackend, SnakeConnectionConfig

config = SnakeConnectionConfig(
    backend=SnakeBackend.POSTGRES,
    name="app",
    host="localhost",
    user="app",
    password="secret",
)
session = await config.open_async()
```

`open_async()` es el gemelo asíncrono de `open()`: elige driver Y dialecto **emparejados** según el
`backend`, así que nadie puede juntar un `AsyncSQLiteDriver` con un `PostgresDialect` — nunca se
escogen las dos piezas por separado.

Si tu aplicación tiene panel de debug, entra por `contrib`: es la misma llamada con el driver
envuelto para que el panel vea el SQL.

```python
from snakeorm.contrib import open_session_async

session = await open_session_async(config)
```

## O lo cableas a mano

```python
from snakeorm import AsyncPsycopgDriver, AsyncSession, PostgresDialect, SnakeQuery

driver = await AsyncPsycopgDriver.connect(dsn)
session = AsyncSession(driver, PostgresDialect())

cars = await session.all(
    SnakeQuery(Car).filter(Car.brand.name == "Seat").include(Car.brand)
)
await session.commit()
```

## Tres motores, tres drivers asíncronos

```python
from snakeorm import AsyncPsycopgDriver, AsyncPyMySQLDriver, AsyncSQLiteDriver

pg     = await AsyncPsycopgDriver.connect(dsn)
mysql  = await AsyncPyMySQLDriver.connect(host="localhost", database="app", user="app")
sqlite = await AsyncSQLiteDriver.connect("./my.db")
```

| Driver | Motor | Cómo habla | Dependencia extra |
|---|---|---|---|
| `AsyncPsycopgDriver` | PostgreSQL | asyncio nativo (psycopg 3) | extra `async` |
| `AsyncPyMySQLDriver` | MySQL / MariaDB | Driver síncrono sobre un hilo propio | extra `mysql` |
| `AsyncSQLiteDriver` | SQLite | Driver síncrono sobre un hilo propio | ninguna |

Los tres son `AsyncDriver`. La sesión no los distingue, y ésa es toda la gracia de la costura — pero
tú mereces saber cuál es cuál, porque no escalan igual.

## Dos de los tres corren sobre un hilo, y conviene que lo sepas

Solo un motor tiene librería asyncio nativa entre las dependencias del proyecto: psycopg 3. Para los
otros dos, `ThreadedAsyncDriver` envuelve un `SnakeDriver` en un `ThreadPoolExecutor(max_workers=1)`
y espera ahí cada llamada.

**No es fingir async.** Es exactamente lo que hace `aiosqlite` por dentro, y para MySQL da
concurrencia REAL: Python suelta el GIL mientras el socket espera, así que dos consultas de dos
tareas distintas se solapan de verdad.

**Y tampoco sale gratis.** No rinde como un protocolo nativo bajo mucha concurrencia, porque **cada
conexión ocupa un hilo del sistema**. Cien conexiones simultáneas son cien hilos. Ése es el número
con el que dimensionar, y es la razón de que aquí el pool importe más, no menos.

!!! info "Un hilo por conexión, y no un pool compartido"

    Una conexión DBAPI no es thread-safe: `sqlite3` lo comprueba y se niega en seco, y PyMySQL
    sencillamente se corrompe si dos hilos la usan a la vez. Con un único hilo por driver, las
    llamadas se serializan por construcción y la conexión ve siempre el mismo hilo. Serializar no
    cuesta nada aquí —una sesión ya espera cada consulta antes de lanzar la siguiente— y quien
    quiera paralelismo abre más conexiones.

    La conexión además se **abre dentro** de ese hilo, porque `sqlite3` ata cada conexión a su hilo
    creador y lanza si otro la toca.

El día que exista un driver nativo para alguno de estos motores, entra como otra implementación del
mismo Protocol y no cambia nada aguas arriba.

## Los modelos y las consultas son los MISMOS

No hay `AsyncModel` ni `AsyncQuery`. `SnakeQuery` no ejecuta —solo emite `(sql, params)`—, así que
**no tiene color** y se reutiliza tal cual. Lo único con color es la costura de ejecución, y ahí vive
`AsyncSession`.

## Paridad

`AsyncSession` expone **exactamente** los mismos métodos públicos que `SnakeSession` (mismo `include`,
`iterate`, `upsert`…). Mismos nombres, con `async def` + `await` y `async with`. Y el comportamiento
también coincide hasta en las esquinas: `add()` rellena el PK autoincremental desde `last_insert_id`
en un motor sin `RETURNING`, y `add_all()` emite el mismo aviso sobre las claves generadas que un
INSERT masivo no puede devolver.

## Decoradores de driver

```python
from snakeorm import AsyncLoggingDriver, AsyncTimeoutDriver, PostgresDialect

driver = AsyncLoggingDriver(driver, write=print)
driver = await AsyncTimeoutDriver.apply_to(driver, PostgresDialect(), statement_timeout_ms=5000)
```

La sesión no se entera de que están ahí.

`AsyncTimeoutDriver` se aplica con `apply_to` y no con el constructor porque tiene que ejecutar un
`SET` en la conexión, y dentro de `__init__` no se puede esperar. La sentencia la pone el dialecto:
Postgres y MySQL tienen una cada uno; SQLite no tiene timeout de servidor, así que `apply_to` se
niega con `SnakeDialectError`.

## Pool

En async es donde un pool se gana el sueldo: un servidor con cien tareas concurrentes abre cien
conexiones si nadie las reparte, y con los drivers sobre hilo eso son además cien hilos.
`AsyncSnakePool` es el espejo de `SnakePool`, con las mismas tres salvaguardas — está en
[varias bases de datos](multi-connection.es.md).

## Migraciones asíncronas

```python
from snakeorm import PostgresDialect
from snakeorm.migration import AsyncMigrationRunner, load

runner = AsyncMigrationRunner(driver, PostgresDialect())
applied = await runner.apply(load("migrations"))
```

!!! warning "Las migraciones de DATOS no corren aquí"

    `RunPython` recibe una `SnakeSession` **síncrona**: su cuerpo bloquearía el bucle de eventos. El
    runner asíncrono **para y lo dice**. Aplica esas migraciones con `MigrationRunner` sobre un driver
    síncrono; las de esquema sí van aquí.

## Cuándo NO usarlo

Si tu aplicación es síncrona, el async no la hace más rápida — solo más difícil de depurar. Tiene
sentido cuando el proceso pasa la mayor parte del tiempo esperando E/S. Un script de carga por lotes
no es ese caso. Y sobre SQLite casi nunca compensa: no hay red que esperar, así que el salto de hilo
no te da nada más que poder estar dentro de un `async def`.

---

Siguiente: [varias bases de datos](multi-connection.es.md).

!!! info "Y lo comprueba la máquina"

    Un test lee los métodos públicos de `SnakeSession` y de `AsyncSession` y los compara. Existe
    porque `AsyncSession` llegó a publicarse con doce de veintidós: dos clases largas no se comparan
    a ojo. Lo mismo vale para `AsyncMigrationRunner` frente a `MigrationRunner`.

