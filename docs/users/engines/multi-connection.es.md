# Varias bases de datos

```python
from snakeorm import SnakeColumn, SnakeModel, snake_auto, snake_model, snake_session, snake_str

@snake_model(table="events", database="analytics")  # tied to another connection
class Event(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_str()

analytics = snake_session("analytics")  # opens the connection by name
```

`database` es **declarativo y estático**: se lee del modelo, no se decide en runtime. No cambia una
coma del SQL — y tampoco encamina nada. Nada de la sesión ni de la query lo lee: una sesión manda a
la conexión con la que SE ABRIÓ, así que abrir una contra `default` y consultar `Event` por ella
emite SQL perfectamente válido contra la base equivocada, sin error y sin aviso. Quien SÍ lee
`database` es `snake_link()`, para rechazar una relación que cruza conexiones, y el `--database` de
la CLI, para elegir las tablas y el historial de migraciones de una conexión. Darle el modelo a la
sesión correcta es cosa tuya: el ORM no tiene encaminador, porque encaminar exigiría adivinar en
ejecución lo que esta etiqueta ya afirma al importar.

## Declarar las conexiones

La `default` sale de `DATABASE_URL` / `SNAKEORM_DSN` / piezas `DB_*`. Las demás van por nombre, en
`SNAKEORM_DSN_<NAME>`:

```bash
DATABASE_URL=postgresql://user:pass@localhost/app
SNAKEORM_DSN_ANALYTICS=postgresql://user:pass@other-host/events
```

!!! note "Si falta un DSN, se dice EXACTAMENTE cuál"

    ```text
    There is no DSN for connection 'analytics': set the environment variable
    SNAKEORM_DSN_ANALYTICS (or put it in the .env). Connection 'default' is the only
    one resolved from the DB_* pieces.
    ```

    Un DSN que se resuelve a ciegas acaba conectando a la base equivocada — peor que no conectar.

### Cada conexión lleva su propio motor

Una conexión con nombre no está atada a PostgreSQL. El motor se LEE, en este orden: un
`SNAKEORM_BACKEND_<NOMBRE>` explícito (o `DB_BACKEND` para la conexión por defecto) y luego el
esquema del propio DSN —`postgresql://`, `mysql://`, `sqlite://`—, porque un esquema es una
declaración y leerlo no es adivinar.

```bash
SNAKEORM_DSN_ANALYTICS=postgresql://user:pass@other-host/events   # engine read off the scheme
SNAKEORM_DSN_ARCHIVO=sqlite:////var/data/archivo.db               # SQLite: FOUR slashes = absolute
SNAKEORM_DSN_LEGACY=mysql://user:pass@old-host:3307/ventas        # MySQL, likewise

SNAKEORM_BACKEND_LEGACY=mysql   # only when you want to say it out loud
```

La cuarta barra del DSN de SQLite no es una errata. La tercera es el separador de la URL, así que
`sqlite:///var/data/archivo.db` nombraría la ruta RELATIVA `var/data/archivo.db`, resuelta contra el
directorio desde el que se arrancara el proceso. Una ruta absoluta lleva cuatro.

Un DSN sin esquema es PostgreSQL, y eso es una derivación y no un defecto a ciegas: la forma
`host=x dbname=y` es la sintaxis de palabras clave de libpq, y no la escribe ningún otro motor.

!!! danger "Un motor mal escrito se rechaza, no se redondea al más parecido"

    ```text
    SNAKEORM_BACKEND_LEGACY='postgress' is not a known engine. The three are:
    postgres, mysql, sqlite. It is refused instead of falling back, because falling
    back means talking to another database without saying so.
    ```

## Abrir sesión

```python
from snakeorm import snake_session

session   = snake_session()  # "default"
analytics = snake_session("analytics")
```

La fábrica monta driver y dialecto desde la configuración.

## Migraciones por conexión

```bash
uv run snakeorm makemigrations --database analytics
uv run snakeorm migrate --database analytics
```

Cada conexión CON NOMBRE tiene su directorio (`migrations/<database>/`) y su numeración propia; la
`default` se queda en `migrations/` a secas, así que un proyecto de una sola base nunca ve cambiar la
estructura bajo los pies. Sin el filtro, `makemigrations` intentaría crear TODAS las tablas en CADA
base.

## Relaciones entre bases: no

```python
@snake_model(table="orders")  # default
class Order(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    event_id: SnakeColumn[int] = snake_int()
    event: SnakeToOne[Event] = snake_to_one(event_id)  # Event lives in "analytics"
```

`snake_link()` **falla al arrancar**, a propósito:

```text
Relationship Order.event crosses databases: Order lives in 'default' and Event in
'analytics'. There is neither a foreign key nor a JOIN possible across connections.
Move one of the two, or store the identifier as a plain column and resolve it
yourself with two queries.
```

Sin la guarda emitiría un `FOREIGN KEY` contra una tabla que no existe en esa base. Si necesitas
cruzar los datos, hazlo en la aplicación: dos consultas y un `dict`.

## Un pool que sobrevive a un despliegue

Prestar conexiones es la parte fácil de un pool. La difícil es **qué pasa cuando la conexión está
podrida y tú no lo sabes**:

```python
from snakeorm import PostgresDialect, SnakeSession, psycopg_pool

pool = psycopg_pool(
    dsn,
    maximum=20,
    pre_ping=True,         # check the pulse before lending
    recycle_seconds=1800,  # drop connections older than 30 min
    timeout_seconds=5,     # wait up to 5 s for one to free up
)

with pool.connection() as driver:
    session = SnakeSession(driver, PostgresDialect())
```

`pool.connection()` es la entrada: te presta el driver y lo devuelve **siempre**, también si el
bloque revienta.

| Perilla | El problema que quita |
|---|---|
| `pre_ping` | La base se reinicia (despliegue, failover) y el pool sigue repartiendo conexiones muertas. Sin esto, el error no sale en el pool: sale en la primera consulta del usuario. Cuesta un viaje de ida y vuelta por préstamo. |
| `recycle_seconds` | El `wait_timeout` de MySQL cierra las ociosas por su cuenta y el pool no se entera. Reciclar por edad no pregunta: previene. |
| `timeout_seconds` | Con el pool agotado, psycopg2 lanza `PoolError` **al instante**. Un pico de tráfico revienta aunque una conexión fuera a liberarse 50 ms después. Con plazo, se espera; agotado, sale un `SnakePoolTimeout`, que tiene nombre propio porque pide otra acción (más pool, menos carga) que un fallo puntual. |

Las tres van **apagadas por defecto**: cuestan viajes o tiran conexiones sanas, y ese precio lo
decide quien conoce su despliegue, no la librería.

Si tres conexiones seguidas vuelven muertas, `acquire()` se rinde con `SnakePoolTimeout` en vez de
girar tirando y pidiendo: a esas alturas la que está caída es la base, no la conexión.

### El mismo pool, en async: `AsyncSnakePool`

`AsyncSnakePool` es el espejo, con las mismas tres salvaguardas y el mismo tope de descartes. En
async el pool importa MÁS, no menos: un servidor con cien tareas concurrentes abre cien conexiones si
nadie las reparte, y una conexión de Postgres cuesta memoria en el servidor aunque esté sin hacer
nada. Con los drivers sobre hilo (MySQL, SQLite) cuesta además un hilo por cabeza.

No hay un gemelo de `psycopg_pool()` para él, porque el pool asíncrono es agnóstico del motor: le das
tres corrutinas —cómo pedir prestada, cómo devolver, cómo cerrarlo todo— y él pone las reglas encima.

```python
import asyncio
from snakeorm import AsyncDriver, AsyncPsycopgDriver, AsyncSession, AsyncSnakePool, PostgresDialect

free: asyncio.Queue[AsyncDriver] = asyncio.Queue()

async def borrow() -> AsyncDriver:
    return free.get_nowait() if not free.empty() else await AsyncPsycopgDriver.connect(dsn)

async def give_back(driver: AsyncDriver) -> None:
    free.put_nowait(driver)

async def close_all() -> None:
    while not free.empty():
        await free.get_nowait().close()

pool = AsyncSnakePool(
    borrow,
    give_back,
    close_all,
    pre_ping=True,
    recycle_seconds=1800,
    timeout_seconds=5,
)

async with pool.connection() as driver:
    session = AsyncSession(driver, PostgresDialect())
```

Dos diferencias con el hermano síncrono, y solo dos:

- Mientras espera a que se libere una conexión, **cede el bucle de eventos** (`asyncio.sleep`) en vez
  de bloquear el hilo. Es lo que hace que una tarea esperando conexión no pare a las otras noventa y
  nueve.
- El `close()` del driver prestado **devuelve** la conexión en vez de cerrarla, y es idempotente. Lo
  segundo no es un detalle: un `close()` repetido —el de la sesión más un `finally` de fuera—
  metería la MISMA conexión dos veces en la cola, y a partir de ahí dos tareas creerían tener cada
  una la suya.

---

Siguiente: [DB-first y scaffolding](db-first.es.md).
