# Depuración: ver el SQL que corre el ORM

Envuelve el driver con `CaptureDriver` y ya puedes contar y ver cada sentencia:

```python
from snakeorm import PostgresDialect, SnakeQuery, SnakeSession
from snakeorm.debug import CaptureDriver, assert_queries

session = SnakeSession(CaptureDriver(driver), PostgresDialect())

with assert_queries(2):                                  # fails unless there are exactly 2
    session.all(SnakeQuery(Maker).include(Maker.trucks))  # 1 root + 1 select-in, no N+1
```

Para async, envuelve con `AsyncCaptureDriver`; todo lo de abajo es igual — la sesión que lo
acompaña está en [Async](../engines/async.es.md).

Ese 1 + 1 vale **hasta el tope de marcadores**: el select-in ata uno por padre, así que pasado el
límite del motor (65.535 en Postgres/MySQL, 32.766 en SQLite) se trocea en lotes y salen más de 2
sentencias.

El **núcleo** (`snakeorm.debug`) es agnóstico del framework; los **adaptadores**
(`snakeorm.contrib`) lo enchufan a FastAPI, Flask o Django.

## Pedirle el plan al motor: `explain()`

Contar sentencias te dice CUÁNTAS. `explain()` te dice qué va a hacer el motor con una de ellas, y
no la ejecuta:

```python
for line in session.explain(SnakeQuery(Widget).filter(Widget.stock == 0)):
    print(line)

# Postgres  -> Seq Scan on widgets  (cost=0.00..16.25 rows=2 width=134)
# SQLite    -> 2 0 0 SCAN widgets
# MySQL     -> 1 SIMPLE widgets ALL ... Using where
```

Las líneas vuelven tal y como las escribe el MOTOR, y eso es una decisión y no dejadez: Postgres
contesta una columna, SQLite cuatro y MySQL una docena, y no comparten ningún campo. Una forma común
sobre los tres sería inventada, no medida.

Cuesta un viaje de ida y vuelta más, y los valores siguen viajando como parámetros. `AsyncSession`
tiene el mismo método con el mismo contrato.

## Inspeccionar el informe

```python
from snakeorm.debug import capture_queries

with capture_queries() as collector:
    session.all(SnakeQuery(Maker))

report = collector.report()
print(report.summary)   # "1 queries · 0.3ms · 0 duplicates"
print(report.to_text())  # a table aligned for the terminal
print(report.slowest())  # the slowest QueryRecord, or None
print(report.warnings)   # one line per duplicated group, naming its file:line
for group in report.duplicates():
    print(f"{group.sql} ran {group.count} times at {group.location}")
```

`capture_queries()` solo recoge lo que pasa por un `CaptureDriver`. Sin el envoltorio el informe
vuelve vacío.

El informe lleva lo que el ORM notó; lo que puede GRITAR —y cuáles de esos te paran— está en
[Errores y avisos](../reference/api/errors.es.md).

## Encenderlo en una petición: `SNAKE_ORM_DEBUG`

Eliges qué ENTREGAS quieres componiendo un conjunto de **canales**:

```bash
SNAKE_ORM_DEBUG=envelope             # one channel
SNAKE_ORM_DEBUG=ssr,envelope,timing  # several; the order does not matter
SNAKE_ORM_DEBUG=                     # empty = off
```

O tipado, en config Python:

```python
from snakeorm.debug import SnakeDebugChannel

SNAKE_ORM_DEBUG = frozenset({
    SnakeDebugChannel.ENVELOPE,
    SnakeDebugChannel.TIMING,
})
```

Un `frozenset`, no una lista: sin duplicados. Un canal desconocido **falla al arrancar**, nunca te
deja sin debug en silencio.

## Los canales

| Canal | Qué entrega | Para quién |
|-------|-------------|-----------|
| `envelope` | Un bloque `snakeorm` dentro del JSON de respuesta | Postman / sin tooling |
| `timing` | La cabecera `Server-Timing` (W3C) | Navegador + devtools |
| `sidecar` | Un token + panel en `/__snake__/{token}` (el informe en JSON con `Accept: application/json`) | Cualquiera, incluidas apps API |
| `ssr` | El panel HTML inyectado en la página | Django / Flask con plantillas |
| `otel` | Spans de observabilidad | Producción (Jaeger/Grafana) |

El canal **es** el interruptor: pon `envelope` en `SNAKE_ORM_DEBUG` y sale en toda respuesta JSON,
sin query param ni flag aparte. Quita el canal y la respuesta va limpia.

## Enchufarlo al framework — una línea

=== "FastAPI"

    ```python
    from snakeorm.contrib import SnakeDebugASGI

    app = SnakeDebugASGI(asgi_app, production=False)
    ```

=== "Flask"

    ```python
    from snakeorm.contrib import SnakeDebugWSGI

    app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, production=False)
    ```

=== "Django"

    ```python
    # settings.py
    MIDDLEWARE = [
        # ...
        "snakeorm.contrib.SnakeDebugMiddleware",
    ]
    ```

El adaptador aplica solo los canales con sentido en su framework: `ssr` en una app API es un no-op que
se **avisa** al arrancar, no se traga en silencio.

## La forma del `envelope`

El debug cuelga de una clave `snakeorm`, **sin corromper la forma**:

```jsonc
// An OBJECT response keeps its keys; `snakeorm` is added as a sibling:
{
  "id": 7,
  "email": "ana@x.com",
  "snakeorm": {
    "summary": "3 queries · 1.2ms · 0 duplicates",
    "request": { "method": "GET", "path": "/users/7", "status": 200, "at": "2026-08-27T10:30:00+00:00" },
    "warnings": [],
    "queries": [
      { "n": 1, "ms": 0.4, "sql": "SELECT ... WHERE id = $1", "params": [7], "rows": 1 }
    ]
  }
}

// An ARRAY response (where you can't add a key) is wrapped under `data`:
{ "data": [ { "id": 1 }, { "id": 2 } ], "snakeorm": { "summary": "1 queries · 0.3ms · 0 duplicates" } }
```

## Ajustar el middleware: `SnakeDebugConfig`

```python
from snakeorm.contrib import SnakeDebugASGI
from snakeorm.debug import SnakeDebugConfig

config = SnakeDebugConfig(
    advise_min_ms=10.0,   # index advisor: ignore anything faster
    csp_nonce=APP_NONCE,  # one value for the whole process; see below
)

app = SnakeDebugASGI(asgi_app, config=config)
```

`advise_min_ms` alimenta al asesor de índices, cuyos hallazgos pinta el panel y expone
`report.index_hints`. `SnakeDebugWSGI` y el middleware de Django reciben el mismo `config=`. Lo que
aconseja se declara en el modelo: ver [Índices y restricciones](indexes-and-constraints.es.md).

**El nonce es para un CSP estricto.** El panel es un `<template>` más un `<script type="module">` en
línea. Bajo `script-src 'self'` el navegador bloquea ese script y el panel sencillamente no aparece:
ni error en el servidor ni nada en la página. Decláralo aquí y pon el mismo valor en tu cabecera CSP;
los tres adaptadores lo llevan hasta el `<script>` del panel. Sin nonce la salida no cambia.

**Por respuesta, solo en Django.** Un `csp_nonce` en la config es UN valor para todo el proceso, y un
CSP estricto quiere uno nuevo por respuesta. Django es el único adaptador con un objeto request al
que preguntar: con [django-csp](https://django-csp.readthedocs.io/) montado se lee `request.csp_nonce`
y **gana** al de la config — no hay que declarar nada. WSGI y ASGI no tienen costura por petición para
esto (ni `environ` ni `scope` llevan convenio de nonce), así que ahí sale el valor de la config.

## El canal `otel`: spans para un trazador de verdad

`otel` es el único canal pensado para **producción**, y el único cuyo lector es una herramienta y no
una persona. Los otros cuatro devuelven el debug por la respuesta — un panel, un bloque JSON, una
cabecera, un token. Éste sale de lado, por OTLP/HTTP, hacia la infraestructura que ya tienes montada.

Instala el extra y apúntalo a tu colector:

```bash
pip install "snakeorm[otel]"

export SNAKE_ORM_DEBUG=otel
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_SERVICE_NAME=my-app
```

Son las variables **estándar** de OpenTelemetry, no una grafía nuestra: si has configurado cualquier
otro exportador, ya las tienes puestas. Sin ellas los spans van a `http://localhost:4318/v1/traces`,
que es el puerto que publica un Jaeger local.

El extra se trae `opentelemetry-api` y nada más — el SDK no. Compra lo único que no se puede
reimplementar: leer el span que tu aplicación ya tiene abierto, para colgar los nuestros de él. La
emisión OTLP en sí es biblioteca estándar.

### La forma de una traza

Un span raíz por petición, un hijo `CLIENT` por consulta, y los agregados en los dos sitios:

| qué | dónde acaba |
|-----|-------------|
| el SQL | `db.query.text` en cada hijo |
| el motor | `db.system.name` (`postgresql` / `mysql` / `sqlite`) |
| la tabla y el verbo | `db.collection.name`, `db.operation.name` |
| el esquema | `db.namespace` — SnakeORM emite `"public"."users"`, y las dos mitades van separadas |
| el nombre del span | `db.query.summary` — `SELECT orders`, nunca la sentencia entera |
| filas | `db.response.returned_rows` |
| el sitio que la lanzó | `code.file.path`, `code.line.number`, `code.function.name` |
| N+1, recuentos, avisos, índices sugeridos | `snakeorm.*` en el RAÍZ, como atributos **y** como eventos |

Un span de consulta se llama como su resumen y NO como su SQL, y eso es lo que sostiene la línea de
tiempo: Jaeger solo pinta insignias de fila para los atributos `http.*`, así que la fila de un span
de base de datos es su nombre y nada más. Un span llamado `SELECT api_tokens` se lee de un vistazo;
uno llamado como la sentencia entera es una línea ilegible. Los atributos `http.*` del RAÍZ sí salen
como insignia: el verbo y el estado aparecen junto al nombre de la petición.

Los hijos son lo que hace útil el **Trace Statistics** de Jaeger: agrupa por `code.line.number` y la
línea que dispara quinientas consultas sale con su porcentaje del coste, en dos clics. Es el mismo
agrupado `(sql, origin)` que el panel ya calcula, re-derivado por el backend y con el reparto de coste
que el panel no da.

El raíz lleva `snakeorm.has_n_plus_one`, que se busca **entre** trazas: «enséñame todas las peticiones
con un N+1» es una pregunta que ni el panel ni un único span-mazacote contestan.

### Dónde va el middleware, y los tres lo escriben distinto

Nuestros spans cuelgan del de la aplicación solo mientras su span de servidor sigue **abierto**. Si
nuestro middleware es el de fuera, ese span ya se ha cerrado cuando entregamos el informe, y las
trazas salen sueltas. **Equivocarse aquí no falla** — los spans llegan, solo que descolgados —, así
que conviene comprobarlo una vez:

| framework | el de fuera es | así que OpenTelemetry va |
|-----------|----------------|--------------------------|
| Django | la **primera** entrada de `MIDDLEWARE` | **encima** de `SnakeDebugMiddleware` |
| Flask | la **última** asignación `app.wsgi_app = ...` | **después** de `SnakeDebugWSGI` |
| FastAPI | la **última** llamada `app.add_middleware(...)` | **después** de `SnakeDebugASGI` |

Django se lee al revés que los otros dos, que es justo por lo que está escrito.

### Qué viaja y qué no

**El SQL viaja; los parámetros no.** La spec recoge por defecto el texto *parametrizado*, «porque al
parametrizar el usuario da una señal fuerte de que lo sensible va en los valores» — y SnakeORM jamás
interpola un valor en una sentencia, así que `db.query.text` no puede llevar datos de usuario por
construcción. Los valores son opt-in, clave a clave, y **no hay variable de entorno** para ellos:
requiere una línea de código, porque una variable de entorno es precisamente el interruptor que
alguien enciende sin querer.

**La emisión nunca ocurre en el hilo de la petición.** Medido contra localhost, exportar en línea añade
~210 ms a una petición de 503 consultas; en el camino asíncrono eso bloquea el event loop entero. Así
que el informe entra en una cola acotada y un hilo de fondo lo publica. Una cola llena descarta y lo
cuenta; un colector inalcanzable avisa **una vez**, nombrando el endpoint, y nunca lanza hacia tu
petición.

**Degrada de tres maneras y ninguna rompe.** Con un proveedor de OpenTelemetry activo, nuestro raíz
cuelga del span de la aplicación. Con la librería instalada pero sin proveedor, y con la librería sin
instalar, nuestro raíz pasa a ser el span de servidor de la petición y la traza se sostiene sola.

## Seguridad: nunca en producción

Tres canales **exponen SQL y parámetros**: `ssr`, `envelope` y `sidecar`. Aunque estén en
`SNAKE_ORM_DEBUG`, en producción se **desactivan**: la config dice qué quieres, el entorno dice qué se
permite. En Django el gate se ata a `settings.DEBUG`; en FastAPI/Flask, al parámetro `production=`
del middleware.

**Y no se adivina nada.** Si uno de los tres está encendido y nadie ha declarado el entorno, el
middleware se niega a arrancar:

```text
SnakeConfigError: These debug channels hand the SQL to whoever asked (ssr) and nothing
declares whether this is production. Set SNAKE_ORM_PRODUCTION=true|false, or pass
production=True/False.
```

`otel` **no** está en esa lista, y la ausencia es deliberada. Lo que hace arriesgados a los otros
tres no es lo que llevan sino **quién lo recibe**: devuelven el debug al cliente por la respuesta
HTTP — y `ssr` es el más ancho, porque pinta el panel dentro de la página con los valores de los
parámetros ya sustituidos en el SQL. `otel`
sale de lado, hacia un colector que el operador ya controla — y producción es el único sitio donde un
canal de trazas justifica existir. Quitarlo ahí sería declararlo muerto.
