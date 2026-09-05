# 🐍 SnakeORM

[![CI](https://github.com/velezanthony/snake-orm/actions/workflows/ci.yml/badge.svg)](https://github.com/velezanthony/snake-orm/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/snake-orm?label=PyPI&color=3775A9)](https://pypi.org/project/snake-orm/)
[![TestPyPI](https://img.shields.io/pypi/v/snake-orm?pypiBaseUrl=https%3A%2F%2Ftest.pypi.org&label=TestPyPI&color=8A8A8A)](https://test.pypi.org/project/snake-orm/)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
![Engines](https://img.shields.io/badge/engines-PostgreSQL%20%7C%20MySQL%20%7C%20SQLite-336791)
![Typing](https://img.shields.io/badge/typing-mypy%20%2B%20pyright-2ea44f)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Navegación profunda de relaciones completamente tipada en Python. Sin codegen. Sin plugin de type-checker.**

Documentación (inglés y castellano): <https://velezanthony.github.io/snake-orm/>

```python
Truck.maker.nation.name == "España"   # SnakeExpr[str] -> SnakeCondition
```

```sql
SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0
JOIN "public"."makers" AS t1  ON t0."maker_id" = t1."id"
JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"
WHERE t2."name" = %s
```

Mypy lo comprueba. Pyright lo comprueba. Pylance lo autocompleta. El equivalente en Django,
`filter(maker__nation__name="España")`, es una cadena: sin autocompletado, sin comprobación, y
renombrar `nation` falla en producción.

---

## Instalación

Requiere Python 3.11+. SQLite viene con la librería estándar, así que no hace falta levantar nada
para empezar.

```bash
pip install --pre snake-orm
```

La distribución es `snake-orm` y el paquete es `snakeorm`: `import snakeorm`. Se publica en
[pypi.org/project/snake-orm](https://pypi.org/project/snake-orm/), y cada versión pasa antes por
[test.pypi.org/project/snake-orm](https://test.pypi.org/project/snake-orm/) — el mismo artefacto,
subido ahí primero, porque una versión aceptada en PyPI está gastada y no se puede reemplazar.

La versión es una **beta**, y para eso está `--pre`: un `pip install snake-orm` a secas no recoge
una preliminar, así que nadie acaba en ella sin querer mientras la API todavía se mueve. Aquí no se
fija un número a propósito — seis páginas lo llevaban escrito y cuatro iban ya una release por
detrás, recomendando la versión que la nueva existe para arreglar.

Desde un checkout, para trabajar sobre el propio ORM:

```bash
uv sync --all-extras --all-groups
uv run pytest          # suite
uv run mypy .          # must pass
uv run ruff check .    # must pass
```

[Instalación](docs/users/getting-started/installation.es.md) →
[primer modelo](docs/users/getting-started/first-model.es.md) →
[migraciones](docs/users/getting-started/migrations.es.md).

```python
@snake_model(table="makers")
class Maker(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)
    nation_id: SnakeColumn[int] = snake_int()
    nation: SnakeToOne[Nation] = snake_to_one(nation_id)
    trucks: SnakeToMany[Truck] = snake_to_many("maker")

snake_link()   # once, after importing every model
```

El tipo sale siempre de la anotación. `snake_column()` solo añade información de SQL.

```bash
uv run snakeorm makemigrations --models myapp.models --name initial
uv run snakeorm migrate --models myapp.models --dsn "host=... dbname=..."
uv run snakeorm rollback --models myapp.models --dsn "..."
```

---

## El mecanismo

**Descriptores recursivos** cuyo `__get__` devuelve un tipo distinto según el acceso:

```python
user.car.name               # instance -> the value           -> str
User.car.brand.name == "x"  # class    -> a SQL expression     -> SnakeCondition
```

`User.car` devuelve `type[Car]`, así que `.brand.name` vuelve a disparar la sobrecarga de clase de
los descriptores de `Car`. El `@dataclass_transform` del decorador tipa el `__init__`. Es el
equivalente manual a los *mapped types* de TypeScript.

El sistema de tipos es la única fuente de verdad: la clase se compila **una vez** a un grafo de
metadata inmutable, y el runtime no vuelve a inspeccionarla.

---

## Por qué Django devuelve `Any`

```python
User.objects.annotate(num_posts=Count("posts"))
user.num_posts   # -> Any
```

`annotate` devuelve «un `User` **más** un `num_posts: int`». Eso es un tipo intersección. TypeScript
lo tiene; Python no. Así que hay tres caminos, y solo tres:

| Camino | Nombres dinámicos | Tipado real | IntelliSense |
|---|---|---|---|
| `__getattr__ -> Any` | ✅ | ❌ | ❌ |
| Nombres declarados | ❌ | ✅ | ✅ |
| Plugin de type-checker | ✅ | ✅ | parcial |

Django eligió el primero y lo parcheó con el tercero (`django-stubs`). SnakeORM prohíbe el tercero
por tesis y toma el segundo, con una salida de emergencia tipada.

`Any` no es tipado, es apagar el checker:

```python
def __getattr__(self, name: str) -> Any: ...
u.agg.count_children * 2           # mypy: 0 errors
other: str = u.agg.count_children  # mypy: 0 errors  <- same value, as a str
```

`object` mantiene el nombre dinámico y despierta al checker:

```python
def __getattr__(self, name: str) -> object: ...
u.agg.count_children * 2           # error: unsupported operand types for *
count: int = cast("int", u.agg.count_children)   # explicit, and signed with your name
```

---

## Estados ilegales que no se pueden escribir

```python
SnakeQuery(Nation).filter(Nation.makers.name == "SEAT")
# error: "SnakeCollection[Maker]" has no attribute "name"  [attr-defined]
```

En Django eso compila, se ejecuta y duplica filas en silencio — que es para lo que existe
`.distinct()`. Un to-many expone **operaciones de colección**, no las columnas del hijo:

```python
q.filter(Nation.makers.any(Maker.name == "SEAT"))  # any?   -> correlated EXISTS
q.filter(~Nation.makers.any())                     # none?  -> NOT EXISTS
q.filter(Nation.makers.count() > 3)                # how many? -> scalar subquery
q.include(Nation.makers)                           # load them -> select-in, 2 queries

q.include(SnakePrefetch(Nation.makers).then(Maker.trucks))
# one query per LEVEL (root + makers + trucks = 3), never one per parent
```

Una fila por padre. `DISTINCT` no hace falta nunca.

```sql
-- Nation.makers.any(Maker.trucks.any(Truck.model == "Ibiza"))
SELECT "id", "name" FROM "public"."nations" WHERE EXISTS (
  SELECT 1 FROM "public"."makers" AS e0 WHERE e0."nation_id" = "nations"."id" AND EXISTS (
    SELECT 1 FROM "public"."trucks" AS e1 WHERE e1."maker_id" = e0."id" AND e1."model" = %s))
```

> **Implícito cuando la respuesta es única. Explícito cuando hay más de una respuesta correcta.**

Un to-one nunca cambia el número de filas, así que el `JOIN` se infiere. Un to-many sí lo cambia,
así que el ORM no adivina.

---

## Lo que la tesis da gratis

**Nada de N+1 en silencio.** Una relación no cargada lanza en vez de consultar:

```python
truck.maker
# SnakeRelationshipNotLoaded: Relation 'maker' was not loaded.
#                             Use .include(Truck.maker) in the query.
```

**No hay `F()`.** El acceso de clase ya es una expresión:

```python
session.update_where(query, [(Counter.views, Counter.views + 1)])
# UPDATE "counters" SET "views" = ("views" + %s) WHERE ...
```

Pares, no un diccionario: `SnakeExpr` no es *hashable* porque su `__eq__` devuelve una
`SnakeCondition`.

**El many-to-many cruza un modelo de verdad**, nunca una tabla implícita:

```python
tags: SnakeToMany["Tag"] = snake_to_many_through(through="PostTag", via="post", to="tag")
```

El puente es un modelo corriente, así que ponerle columnas extra son campos corrientes desde el
primer día.

**Un `UPDATE`/`DELETE` masivo usa el filtro y nada más.** Sin `WHERE` se rechaza, y también se
rechaza cualquier otro botón que hayas puesto en la misma consulta — `limit()`, `order_by()`,
`only()`. Tirar lo que pediste contestaría otra pregunta sin decirlo: selecciona las filas
primero y escribe por clave primaria.

**`annotate()` cuenta con una subconsulta correlacionada, no con un `LEFT JOIN`** — un padre sin
hijos sale con `0` en vez de desaparecer.

**Una vista es un modelo de solo lectura, y es navegable.** `@snake_view` mapea una `VIEW` con
columnas tipadas, navegable en los dos sentidos; `session.add/update/delete` la rechazan en el
**tipo**, porque escribir exige un `SnakeModel`. Crearla, alterarla y borrarla vive en las
migraciones (`CreateView`/`AlterView`/`DropView`).

**El histórico de migraciones se escribe en `.py`**, porque `python_type` es un `type` de Python. En
JSON haría falta un registro nombre↔tipo: un segundo sistema de tipos, paralelo al de Python y peor
que él.

---

## Anotaciones tipadas

Declaras la clase del resultado — tú eliges el nombre, Python elige el tipo:

```python
@snake_result
class RealmStats(SnakeResult[Realm]):
    realm: Realm
    forge_count: int

rows = session.annotate(query, RealmStats, forge_count=Realm.forges.count())
rows[0].forge_count  # int, with IntelliSense
rows[0].realm.name   # str, navigation intact
```

Para nombres genuinamente dinámicos, la salida de emergencia es explícita:

```python
count = cast("int", realm.aggregate.forge_count)   # object -> the cast is mandatory
```

Sin el cast no compila. Sin anotar, lanza `SnakeAggregateNotLoaded` nombrando los agregados que sí
tiene.

---

## Qué hay dentro

| | |
|---|---|
| **Consultas** | filter · order/limit/offset · group by/having · agregados · `annotate` · joins explícitos · `include` (to-one y to-many) · navegación profunda · `.any()` · subconsultas correlacionadas · `IN` compuesto · `only`/`defer` · `iterate` (cursor de servidor) · `for_update` · `raw` |
| **SQL** | window functions con frame · `UNION`/`INTERSECT`/`EXCEPT` · `WITH RECURSIVE` · `CASE`/`COALESCE`/`NULLIF` · funciones de texto, fecha y matemáticas · `json_get` · `ILIKE` |
| **Escrituras** | insert/update/delete · upsert · masivas · `RETURNING` · savepoints · niveles de aislamiento · reintento ante conflicto transitorio · `refresh` |
| **Esquema** | PK y FK compuestas · herencia polimórfica · vistas · triggers · índices (parciales, funcionales, `GIN`/`GIST`/`BRIN`) · checks · comentarios · enums · conversores propios |
| **Motores** | PostgreSQL · MySQL/MariaDB · SQLite, los tres de primera clase · catálogo `Cap` (`Full`/`Degraded`/`Nope`) · drivers síncronos y asíncronos · pool con `pre_ping`/`recycle`/timeout · statement timeout · `EXPLAIN` |
| **Migraciones** | diff autodetectado · runner atómico · `RebuildTable` para SQLite · `RunPython` con reverso · squash · dependencias entre apps · detección de deriva contra la base de datos real |
| **Herramientas** | introspección y scaffold en los tres motores · panel de debug (`ssr`, `envelope`, `timing`, `sidecar`, `otel`) · asesor de índices · contrib WSGI/ASGI/Django · CLI |

Fila a fila, con enlaces al código, al test y a la página: [índice de features](docs/features.es.md).

---

## Arquitectura

```
Python class → Model Compiler → immutable metadata graph
                                        ↓
        SQL · migrations · query · session · CLI
```

```
decorators/  metadata/  compiler/  registry/  linker/
query/  expressions/  sql/  dialects/  drivers/  session/  migration/  cli/
```

Dos ejes que nunca se mezclan: el **dialecto** decide cómo se *escribe* el SQL (placeholders,
quoting, `RETURNING`, `ON CONFLICT`); el **driver** decide cómo se *ejecuta*. Los modelos y el grafo
son agnósticos del motor — que algo específico de Postgres llegue al modelo es un bug.

El SQL va siempre parametrizado: la emisión devuelve `(sql, params)` y los valores nunca entran en
la cadena. Eso mata la inyección, y es lo que hace posible el multi-motor.

El async reutiliza el núcleo entero: la generación de SQL no ejecuta, así que no tiene color.

El detalle está en [arquitectura](docs/contributors/architecture.es.md); cómo se trabaja aquí, en
[CONTRIBUTING](CONTRIBUTING.es.md).

---

## El contrato de tipos es un test

En `test/typing/`:

- `cases_positive.py` — lo que **debe** tipar, con `assert_type`.
- `cases_negative.py` — lo que **no debe** compilar, cada línea con su `# EXPECT: <code>`.
- El runner exige que mypy reporte exactamente esos errores en exactamente esas líneas, y que
  pyright rechace los mismos.

Rompe `Truck.maker.nation.name` y la suite falla.

---

## Lo que NO se ha construido, a propósito

- **Identity map y unit of work.** Dos consultas a la misma fila devuelven dos objetos. Las
  escrituras son explícitas; nada se vuelca a tus espaldas.
- **Lazy loading.** Tocar una relación no cargada lanza. Es lo que hace imposible el N+1 por
  defecto.
- **Herencia joined-table.** La tabla única con discriminador cubre el polimorfismo, y su precio es
  una regla: las columnas propias de un hijo tienen que admitir `NULL`.
- **Orden por defecto del modelo.** Un `ORDER BY` escondido que no escribiste.

## Límites conocidos

- `storage=NATIVE` en `snake_enum` (el `CREATE TYPE` de Postgres) no está construido: `ALTER TYPE
  ... ADD VALUE` no tiene inverso, así que su `down_sql` sería mentira. El `CHECK` por defecto sí es
  reversible.
- Los CHECKs se declaran fuera del cuerpo de la clase (`snake_checks(User, ...)`). Dentro, todavía
  no ha corrido `__set_name__` y la columna no sabe cómo se llama.
- Una expresión no lleva su modelo en el tipo: `Maker.id` y `Truck.id` son gemelas para el checker.
  Codificar el dueño rompería la navegación profunda y la composición de condiciones; donde importa
  (agregados, `.any()`) se valida en runtime.
- No hay lazy loading, ni búsqueda de texto completo, ni operadores de contención de JSON, ni
  operadores de arrays con API tipada.

La lista completa y al día es [límites conocidos](docs/users/reference/limits.es.md) — parte del
contrato, no una lista de disculpas.

---

## Estado

No está publicado en PyPI. La distribución se llama `snake-orm` y el nombre de import es
`snakeorm`; las dos cosas se explican en [release](docs/contributors/release.es.md).

Todo lo de arriba está implementado y probado contra PostgreSQL, MySQL/MariaDB y SQLite de verdad.
No ha corrido en producción todavía, y eso es lo único que un repositorio no puede darse a sí mismo.
