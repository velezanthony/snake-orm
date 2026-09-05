# examples/ — SnakeORM en acción

Documentación viva y ejecutable de SnakeORM. Un dominio editorial (`showcase.py`) que ejercita TODA
la sintaxis, y un recorrido (`tour.py`) que se conecta a un Postgres de verdad, crea el esquema, lo
siembra y pasea por la API imprimiendo, para cada operación, **el SQL emitido** y **el resultado
real**.

## Qué hay aquí

- **`showcase.py`** — el dominio. Modelos (`Ex*`, tablas `ex_*`) que enseñan PKs automáticas y
  explícitas, PKs y FKs **compuestas**, many-to-many con tabla puente **explícita**, columnas
  `UUID`/`Decimal`, `default` literal frente a `default_factory`, `name=` (sobrescritura del SQL),
  `db_comment`, `index=` y un índice único compuesto (`SnakeIndexes`), y **herencia de columnas**
  desde una base abstracta (`ExTimestamped`, sin `@snake_model`, de la que heredan `ExTag` y
  `ExNote`), más una **VIEW** de solo lectura (`ExCatalogEntry`, tabla `ex_catalog`) navegable en los
  dos sentidos. Incluye `create_schema()` (el DDL generado desde la metadata con los emisores de
  `snakeorm.migration`, sin SQL escrito a mano, `CREATE VIEW` incluido) y `seed()`. También incluye
  una **FUNCIÓN DE BASE DE DATOS** (`ex_book_stats`, SQL opaco) y su forma declarada con `@snake_row`
  (`BookStats`) para `session.call`.
- **`tour.py`** — el recorrido, en 22 secciones numeradas. `main()` lo ejecuta de principio a fin.

## Cómo se ejecuta

```bash
uv run python -m examples.tour
```

Necesita un **PostgreSQL** accesible. La conexión la resuelve `test/scenarios/db.py::dsn()`, que lee
un `.env` (o el entorno) buscando `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` (los
valores por defecto del devcontainer). Sin base de datos, esa orden muere con `OperationalError` y
código de salida 1.

Las aserciones sobre la salida viven aparte, y **se saltan solas cuando no hay servidor**:

```bash
uv run pytest src/test/examples -q       # the tour's integration test: SKIPS without Postgres
```

Ese salto es cómodo en un portátil y es un verde que miente dentro de una puerta, así que el Makefile
corre las dos mitades EXIGIENDO el motor — la orden publicada arriba y el test con
`SNAKEORM_REQUIRE_POSTGRES=true`, que convierte el salto en un fallo:

```bash
make examples                            # part of `make audit`
```

> El registro de SnakeORM es un **singleton global**: por eso las clases (`Ex*`) y las tablas
> (`ex_*`) llevan un prefijo único, para no chocar con los modelos de los tests.

## Qué demuestra cada sección

| Sección | Funcionalidad |
| ------- | ------- |
| 1  | CRUD: `add` (RETURNING ancho: PK automática + `default_factory`), `add_all`, `update`, `delete`, `first`, `all` |
| 2  | Filtros: comparadores, `in_`, `like`, `is_null`, `== None`, composición con `&` `\|` `~` |
| 3  | `order_by` (asc/desc), `limit`, `offset`, `distinct()` |
| 4  | **Navegación profunda tipada** (`ExPrinting.edition.book.publisher.country.name`) y sus JOINs |
| 5  | `include()` to-one (LEFT JOIN), to-many (select-in) y la guarda `SnakeRelationshipNotLoaded` |
| 6  | Colecciones: `.any()`, `~.any()`, `.any()` **anidado**, `.count()`, `.avg()`, `.sum_()`, `.count() == 0` |
| 7  | `count()` y `exists()` de la sesión |
| 8  | Proyección: `select()` con columnas, agregados y navegación; `group_by` + `having` |
| 9  | `annotate()` con `@snake_result` + la salida de emergencia `obj.aggregate.<name>` (con un `cast`) |
| 10 | Escritura masiva: `update_where` con aritmética (`col = col + x`) y `delete_where` |
| 11 | `upsert` (DO UPDATE y DO NOTHING) |
| 12 | Subconsulta: `in_(query.as_scalar(col))` |
| 13 | Many-to-many navegando la tabla puente explícita |
| 14 | FK/PK **compuestas**: JOIN compuesto e `include` compuesto (select-in por tupla) |
| 15 | Las **guardas** como funcionalidad: `SnakeRelationshipNotLoaded`, `delete_where` sin filtro, `annotate` con nombres que no casan, y la guarda de tipado (`# does not compile`) |
| 16 | Coerción: una columna `UUID` proyectada vuelve como `uuid.UUID`, no como `str` |
| 17 | `server_default`: el valor lo pone el SERVIDOR (`NOW`, `UUID_V4`), fuera del `INSERT` |
| 18 | **JOIN explícito** a una colección (`.join()`): las **filas hijas**, multiplicadas, frente a `.any()`; `SnakeJoinedQuery` solo proyecta tuplas (no hidrata modelos) |
| 19 | **`include()` anidado** con `SnakePrefetch(...).then(...)`: to-many → to-many con **una consulta por nivel** (select-in encadenado, sin N+1); y **`.filter()` en el prefetch** para acotar qué hijos se cargan en cada nivel (un padre sin hijos que casen vuelve con una lista **vacía**) |
| 20 | **Herencia de columnas**: `ExTag` y `ExNote` heredan `id` + `created_at` de una base abstracta (`ExTimestamped`, sin `@snake_model`); el compilador recorre el MRO y las columnas heredadas salen antes que las propias |
| 21 | **Vistas** (`@snake_view`): un modelo de **solo lectura** mapeado sobre una `VIEW`; se consulta y se **navega** en los dos sentidos (`ExPublisher.catalog` ↔ `ExCatalogEntry.publisher`); `session.add/update/delete` la rechazan (bloqueo en el tipo + guarda en runtime) |
| 22 | **Funciones de base de datos** (`session.call`): llama a una `FUNCTION ... RETURNS TABLE` y mapea sus filas a un `@snake_row` (un contrato **DECLARADO**, no verificado); los ARGS viajan parametrizados; los tipos se coercionan (NUMERIC→`float`). El CRUD de rutinas vive en las migraciones (`CreateFunction`/`AlterFunction`/`DropFunction`) |
