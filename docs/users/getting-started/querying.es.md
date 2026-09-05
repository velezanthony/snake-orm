# Consultar

`SnakeQuery(Modelo)` construye; `SnakeSession` ejecuta. **Construir no ejecuta**: un `SnakeQuery` es
inmutable y no ha tocado la base.

```python
from snakeorm import SnakeQuery, SnakeSession, PostgresDialect, PsycopgDriver

dsn = "postgresql://user:pass@localhost/mydb"
session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())

active_users = session.all(
    SnakeQuery(User).filter(User.active == True).order_by(User.email)
)
```

Cada método devuelve una consulta **nueva**; la anterior no se toca:

```python
base = SnakeQuery(User).filter(User.active == True)
first_page = session.all(base.limit(10))
how_many   = session.count(base)  # `base` stays intact
```

## Leer

| Llamada | Devuelve |
|---|---|
| `session.all(query)` | `list[T]` |
| `session.first(query)` | `T \| None` |
| `session.count(query)` | `int` |
| `session.exists(query)` | `bool` |

No hay `session.get(...)`. Para una fila por PK, usa `first()` con un filtro.

## Filtrar

Operadores de Python sobre los atributos de **clase**:

```python
SnakeQuery(User).filter(
    User.email.like("%@company.com"),
    User.created_at > cutoff,  # implicit AND between arguments
)
```

Repertorio: `==`, `!=`, `<`, `<=`, `>`, `>=`, `.in_()`, `.not_in()`, `.like()`, `.ilike()`,
`.startswith()`, `.endswith()`, `.between()`, `.is_null()`, `.is_not_null()`. Combínalas con `&`
(AND), `|` (OR), `~` (NOT), **siempre con paréntesis**:

```python
SnakeQuery(User).filter((User.active == True) & ~User.nickname.is_null())
```

El lado derecho puede ser **otra columna**, y no cuesta ningún parámetro: una referencia a columna es
parte de la sentencia, no un valor que viaje al lado:

```python
SnakeQuery(Stock).filter(Stock.quantity > Stock.reserved)
SnakeQuery(Stock).filter(Stock.quantity - Stock.reserved > minimum)
```

El par sigue tipado: comparar una columna `int` contra una `str` lo rechaza el checker, que es el
error por el que esto merece la pena. La aritmética compone igual, y siempre lo hizo.

!!! danger "El SQL SIEMPRE va parametrizado"

    Los valores nunca se interpolan: la emisión devuelve `(sql, params)` y el driver los manda por
    separado. Mata la inyección de SQL y habilita el multi-motor: los placeholders (`%s`, `?`, `$1`)
    son justo lo que cambia entre motores.

### Leer dentro de una columna JSON

```python
SnakeQuery(Doc).filter(Doc.meta.json_get("size", as_type=int) > 100)
SnakeQuery(Doc).filter(Doc.meta.json_get("owner", "name", as_type=str) == "ada")
```

`as_type` es obligatorio, y no es ceremonia. Lo que un motor devuelve de un documento es TEXTO, así
que sin tipo declarado esa primera línea sería una comparación de texto — y como texto, `'9' > '100'`
es cierto. El tipo declarado es lo que hace que el ORM emita el cast.

Varias claves recorren una ruta anidada en UN solo acceso. Cada motor lo escribe a su manera (`->>` y
`#>>`, `JSON_EXTRACT` con un unquote, `json_extract`); lo escribe el dialecto, no tú.

!!! warning "El documento no lo comprueba el ORM"

    Si no contiene lo que declaraste, lo dice el MOTOR. SnakeORM no puede saber qué hay dentro de un
    documento que no escribió, y adivinarlo es lo único que no hace nunca.

### Traer media fila

Sobre una tabla ancha, `only()` nombra las columnas que traer y `defer()` las que dejar. La clave
primaria viaja siempre: una fila sin identidad no se puede reescribir ni casar con sus relaciones.

```python
session.all(SnakeQuery(Visit).only(Visit.path))     # + the primary key, always
session.all(SnakeQuery(Visit).defer(Visit.agent))   # everything except that one
```

Leer una columna que se quedó fuera lanza `SnakeColumnNotLoaded` — no vuelve como `None`. Esa
negativa es la funcionalidad: un valor que nadie cargó no puede parecerse nunca a un valor.

`only()` / `defer()` NO se combina con `include()`: la pareja lanza `SnakeUnsupportedFeature` en vez
de tirar en silencio las columnas que nombraste. Usa `select(...)` si lo que quieres son valores.

!!! tip "Casi siempre lo que quieres es `select()`"

    Si lo que necesitas son los VALORES, `session.select(query, Visit.path, Visit.ms)` da tuplas
    tipadas, no cuesta ninguna instancia a medias y no puede levantar después. `only()` es para
    cuando lo que quieres ES el modelo — para dárselo a código que espera uno.

!!! warning "Una fila parcial no se puede reescribir"

    `session.update(row)` sobre una fila construida con `only()`/`defer()` lanza
    `SnakeColumnNotLoaded`: el UPDATE cubre todas las columnas que no son PK y las que dejaste fuera
    no están para mandarlas. Que viaje la clave primaria no salva nada — con PK y todo, la única
    escritura que sobrevive es `session.delete(row)`. Y `update_where` tampoco es escapatoria,
    porque `only()` es uno de los botones que el guardia de escritura masiva rechaza.

    Si necesitas escribir, lee la fila entera, o usa `select()` y luego `update_where` por clave
    primaria.

## Navegar relaciones

Lo que distingue a este ORM:

```python
SnakeQuery(Car).filter(Car.brand.country.name == "Spain")
```

Sin cadenas mágicas y sin `join()` a mano: los JOIN salen del camino navegado, cada salto
comprobado por el type-checker.

## Traer los relacionados

Navegar filtra; para **traer** los objetos relacionados, pídelo con `.include()`:

```python
cars = session.all(SnakeQuery(Car).include(Car.brand))
cars[0].brand.name  # already loaded, no second query
```

Sin `include`, tocar `car.brand` lanza `SnakeRelationshipNotLoaded` en vez de disparar una consulta a
tus espaldas. Así se evita el N+1 por defecto: **el ORM no va a la base sin que se lo pidas**.

```python
session.all(SnakeQuery(Car).include(Car.brand.country))  # to-one: LEFT JOIN
session.all(SnakeQuery(Brand).include(Brand.cars))      # to-many: select-in, not a JOIN
```

El select-in de a-muchos se trocea para caber en el tope de marcadores del motor, así que un lote
grande de padres cuesta varias segundas consultas en vez de una que el driver rechazaría.

## Proyectar y agregar

Cuando no quieres el objeto entero, `select()` devuelve **tuplas**:

```python
from decimal import Decimal
from snakeorm import SnakeQuery, count, sum_

gq = SnakeQuery(Car).group_by(Car.brand_id).having(count() > 1)
rows = session.select(gq, Car.brand_id, count(), sum_(Car.price))
# list[tuple[int, int, Decimal | None]]  -> rows[0][1] is int, not Any
```

Para objetos tipados en vez de tuplas, `session.annotate(query, ResultClass, **aggregates)` agrupa
por la PK del modelo base.

!!! note "`sum_`, `avg`, `min_` y `max_` devuelven un tipo NULABLE"

    Porque SQL lo dice: sobre cero filas devuelven `NULL`, no `0`. Por eso te obligan a escribir
    `Decimal | None`. `count()` sí es `int`: sobre cero filas devuelve `0`.

## Ordenar, paginar, deduplicar

```python
SnakeQuery(User).order_by(User.email.desc())
SnakeQuery(User).order_by(User.nickname.asc().nulls_last())
SnakeQuery(User).limit(20).offset(40)
SnakeQuery(User).distinct()
```

!!! tip "`NULLS FIRST/LAST` no se escribe salvo que lo pidas"

    Sin `.nulls_first()` / `.nulls_last()` manda el defecto del motor, que **no es el mismo** en
    todos. Inventar un comportamiento no pedido sería peor.

!!! info "MySQL y MariaDB reciben otra escritura, y las mismas filas"

    Ninguno tiene la palabra `NULLS LAST` —los dos contestan `ERROR 1064`—, así que el ORM escribe
    la forma portable, `ORDER BY (nickname IS NULL) ASC, nickname ASC`. Preguntas igual en los tres
    motores y las filas vuelven en el mismo orden; lo que cambia es una clave de orden de más en el
    SQL emitido.

!!! danger "`count()` rechaza `distinct()` y `group_by()`"

    No es una limitación: es un rechazo, y merece entenderse. Un `COUNT(*)` sobre una consulta que
    deduplica o agrupa es un número DISTINTO del que devolvería esa consulta: filas, no filas
    distintas; filas, no grupos. Contestar lo primero en silencio cuando pediste lo segundo es el
    error que acaba dentro de un paginador enseñando mal el número de páginas durante meses.

    **`limit()` y `offset()` son la excepción, y ésos SÍ se tiran en silencio.** Un `COUNT` está para
    contestar «cuántos hay», así que la página que pediste se ignora a propósito — que es lo que hace
    correcto poner `session.count(base)` al lado de `session.all(base.limit(10))`. Se dice en alto
    porque el borde es afilado: `session.exists(query.limit(0))` contesta **True**, sobre una
    consulta que no puede devolver ni una fila.

    ```python
    users = SnakeQuery(User).distinct()
    session.all(users)               # the distinct rows
    session.count(users)             # refused: this number would not be theirs

    # Ask for the count of what you actually want counted
    distinct_emails = session.select(SnakeQuery(User).group_by(User.email), User.email)
    ```

    Misma regla para `all()` con `group_by()`: una agrupación solo tiene respuesta como
    **proyección**, así que va por `select()`, que es donde columnas y agregados pueden convivir.

## Recorrer mucho sin cargarlo todo

`all()` construye una lista con **todas** las filas antes de devolver la primera. Sobre diez
millones de filas eso son diez millones de tuplas y diez millones de objetos en memoria, y a nadie
le hace falta ver más de una a la vez para exportarlas.

```python
for invoice in session.iterate(SnakeQuery(Invoice), chunk=500):
    export(invoice)
```

El resultado se queda en el motor (un cursor del servidor en Postgres y MySQL) y solo viajan `chunk`
filas por vez. Es **perezoso**: no se ejecuta nada hasta pedir la primera fila, así que cortar con un
`break` no paga el resto. En async es igual, con `async for`.

!!! warning "No convive con un `include()` de a-muchos"

    `iterate()` **lanza** si le pasas un `include()` de a-muchos o un prefetch. El select-in necesita
    TODAS las raíces para lanzar su segunda consulta, y aquí las filas van saliendo de una en una.
    Servírtelo exigiría materializarlas (que es lo que querías evitar) o una consulta por fila (un
    N+1). Las dos traicionan lo que pediste, así que se dice en voz alta en vez de decidir por ti.

    El `include()` de **a-uno** sí funciona: viaja en el mismo JOIN, fila a fila.

## Escribir

```python
user = User(email="ana@x.com", nickname="ana")
session.add(user)  # INSERT; fills the generated id
user.nickname = "anita"
session.update(user)  # UPDATE ... WHERE pk = ...
session.delete(user)
session.commit()
```

`commit()` cierra la transacción; `rollback()`, `savepoint()` y `set_isolation()` están en
[transacciones](../guide/transactions.es.md).

`add()` rellena el id generado, pero **no por el mismo camino en todos los motores**. Donde hay
`RETURNING` (PostgreSQL y SQLite), el INSERT devuelve las columnas del servidor en la misma ida y
vuelta. MySQL/MariaDB no tiene `RETURNING`: ahí el id autoincremental sale de `last_insert_id`, que
se le pregunta a la conexión justo después de escribir. Para ti el resultado es idéntico —`user.id`
tiene valor— y la diferencia solo asoma en masa, que es la sección siguiente.

En masa. `update_where` recibe una **secuencia de pares** `(columna, valor)`, no un dict:

```python
session.add_all([u1, u2, u3])
session.update_where(
    SnakeQuery(User).filter(User.active == False),
    [(User.active, True)],
)
session.delete_where(SnakeQuery(User).filter(User.created_at < cutoff))
```

!!! warning "Una escritura masiva usa el FILTRO, y nada más"

    `update_where`/`delete_where` emiten el `WHERE` y ningún otro botón. Cualquier otro que hayas
    puesto en la misma consulta se **rechaza** con `SnakeUnsupportedFeature` — `limit()`, `offset()`,
    `order_by()`, `only()`, `distinct()`, `for_update()`. No es que se ignoren: tirar lo que pediste
    contestaría otra pregunta sin decirlo.

    ```text
    a bulk DELETE only uses the filter (WHERE), and it does not emit limit(). Dropping what
    you asked for would answer a different question without saying so: select the rows first
    if you need those, then write by primary key.
    ```

    `limit()` es el que duele, porque borrar por lotes es justo lo que uno teclea. Y **sin filtro
    ninguno** también se rechaza: un `DELETE` sin `WHERE` se llevaría la tabla entera.

!!! warning "Sin `RETURNING`, `add_all()` NO rellena las PK autoincrementales"

    En MySQL/MariaDB las filas SÍ se insertan; lo que queda vacío es el `id` **en memoria**. Y no hay
    con qué rellenarlo: `last_insert_id` habla de UNA fila, y que los ids de un INSERT múltiple
    salgan consecutivos depende del servidor, no del ORM. Adivinar ahí sería escribir claves ajenas
    en silencio.

    Por eso el ORM **avisa** en vez de prohibir, una vez por motor. **Si necesitas los ids después,
    usa `add()` por instancia.** Ése es todo el remedio.

!!! warning "La escritura masiva NO dispara señales"

    Un `update_where` es UNA sentencia SQL: no hay objetos que notificar. Si tienes señales
    registradas, el ORM te lo **avisa**. Ver [señales y triggers](../guide/signals-and-triggers.es.md).

---

Siguiente: [migraciones](migrations.es.md), o salta a
[consultas avanzadas](../guide/advanced-queries.es.md) si ya vas con soltura.
