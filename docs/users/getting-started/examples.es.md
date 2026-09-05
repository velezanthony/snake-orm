# Ejemplos ejecutables

Cada página de este sitio es prosa sobre SQL. `src/examples/` es lo contrario: un programa que se
ejecuta, contra un PostgreSQL de verdad, y que imprime para cada operación **el SQL emitido** y **el
resultado real que devuelve la base de datos**, uno al lado del otro.

```bash
uv run python -m examples.tour
```

Eso es el recorrido. Conecta, crea el esquema de un dominio editorial, lo siembra y recorre la API en
secciones numeradas — del CRUD al prefetch anidado, pasando por navegación profunda tipada, claves
compuestas, upsert, vistas y funciones de base de datos.

## Qué vive ahí

| Fichero | Qué es |
|---|---|
| `src/examples/showcase.py` | El dominio. Modelos `Ex*` sobre tablas `ex_*`, más `create_schema()` y `seed()` |
| `src/examples/tour.py` | El recorrido. `main()` lo ejecuta de principio a fin |
| `src/examples/README.md` | La tabla de qué sección demuestra qué |

El dominio no es un juguete: ejercita claves primarias automáticas y explícitas, PK y FK
**compuestas**, un many-to-many con tabla de unión explícita, columnas `UUID` y `Decimal`, `default`
literal frente a `default_factory`, renombrado de columnas, comentarios, índices, columnas
**heredadas** de una base abstracta, una **VISTA** de solo lectura navegable en ambos sentidos y una
**FUNCIÓN** de base de datos llamada con `session.call`.

`create_schema()` merece una mirada aparte: el DDL sale de la metadata a través de los emisores de
`snakeorm.migration`, incluido el `CREATE VIEW`. Ahí dentro no hay SQL escrito a mano.

## Qué necesita

Un PostgreSQL accesible. La conexión la resuelve `test/scenarios/db.py::dsn()`, que lee el mismo
`.env` que el resto del proyecto (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`). La
[página de instalación](installation.es.md) cubre esas variables.

El registry de SnakeORM es un **singleton global**, y por eso cada clase y cada tabla de ahí llevan
un prefijo único (`Ex*`, `ex_*`): para que no puedan colisionar con los modelos de la suite de tests.

Hay un test de integración que ejecuta el recorrido entero:

```bash
uv run pytest src/test/examples/ -q
```

## Por qué leerlo en vez de leer una página

Porque una página se queda atrás y un programa no. El SQL que imprime el recorrido no es una
ilustración del SQL que se ejecuta: **es** el SQL que se ejecuta, sacado del mismo emisor que usa la
sesión. Si cambia un emisor, cambia la salida con él.

La sección de los guards es el caso más claro. Provoca los errores a propósito —una relación sin
cargar, un `delete_where` sin filtro, un `annotate` con nombres que no casan— e imprime los mensajes.
En un ORM cuya doctrina es gritar en vez de adivinar, esos mensajes son el producto, y ahí están,
impresos por lo mismo que los emite.

## Benchmarks

`src/benchmarks/` es el otro rincón ejecutable: un harness autocontenido que cronometra la
compilación, la emisión de SQL, las inserciones, las lecturas, la navegación profunda, el prefetch
select-in y los agregados contra un PostgreSQL real.

```bash
uv run python -m benchmarks.run
```

Crea su propio esquema (`bench_*`), mide, y lo borra. Lee `src/benchmarks/README.md` antes de leer
los números: es un **baseline propio**, sobre una máquina y un motor, sin comparación con otros ORMs
— sirve para cazar regresiones, no para afirmar un ranking.

---

Siguiente: la [guía](../guide/columns.es.md), que va tipo por tipo.
