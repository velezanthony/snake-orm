# Consultas avanzadas

Cuando `.filter()` se queda corto: expresiones, ventanas, compuestas, recursivas, bloqueo y SQL crudo.

## Expresiones condicionales

```python
from snakeorm import snake_case, snake_coalesce, snake_nullif

tag = snake_case(
    (Order.total > 1000, "large"),
    (Order.total > 100, "medium"),
    default="small",
)
visible = snake_coalesce(User.nickname, User.email)  # the first one that is not null
safe = snake_nullif(Order.discount, 0)               # NULL when it is 0

session.select(SnakeQuery(Order), Order.id, tag, safe)
```

Las tres son `SnakeValue`: se comparan, proyectan y ordenan como una columna. Son valores, no filas,
así que quien las ejecuta es `session.select()`; `all()` no las acepta.

## Funciones de ventana

```python
from snakeorm import dense_rank, lag, lead, rank, row_number, sum_

position = row_number().over(
    partition_by=[Sale.region],
    order_by=[Sale.amount.desc()],
)
previous = lag(Sale.amount)
running = sum_(Sale.amount).over(order_by=[Sale.sold_on.asc()])

session.select(SnakeQuery(Sale), Sale.region, position, running)
```

| Función | Devuelve | Empates |
|---|---|---|
| `row_number()` | `int` | Sin empates: 1, 2, 3, 4 |
| `rank()` | `int` | Con empates y huecos: 1, 2, 2, 4 |
| `dense_rank()` | `int` | Con empates, sin huecos: 1, 2, 2, 3 |
| `lag(v, n)` / `lead(v, n)` | `T \| None` | Opcional: en las primeras `n` filas no hay fila anterior |

## Compuestas: UNION, INTERSECT, EXCEPT

```python
active = SnakeQuery(User).filter(User.active == True)
recent = SnakeQuery(User).filter(User.created_at > cutoff)

session.all(active.union(recent))      # no duplicates
session.all(active.union_all(recent))  # duplicates kept, and cheaper for it
session.all(active.intersect(recent))
session.all(active.except_(recent))
```

!!! danger "Las ramas tienen que ser del MISMO modelo"

    Mezclar modelos distintos hidrataría filas en los atributos equivocados sin un solo error. El ORM
    lo rechaza en tiempo de ejecución.

!!! note "En SQLite una rama no lleva nada propio"

    SQLite rechaza los paréntesis alrededor de las ramas, y sin ellos el `limit()`, el `offset()` o el
    `order_by()` de una rama se aplicarían al conjunto entero. El dialecto lo declara y la emisión
    lanza `SnakeEmitError` en vez de contestar otra pregunta. Ordena y acota el resultado, no la rama.

!!! danger "En SQLite una rama no puede ser un conjunto ELLA MISMA, salvo encadenando a la izquierda"

    `a.union(b.except_(c))` mete un conjunto entero en la rama derecha. Sin los paréntesis SQLite lee
    los operadores de izquierda a derecha, así que eso pasa a ser `(a UNION b) EXCEPT c`: SQL válido,
    filas distintas, ningún error. Medido sobre la matriz 4x4 entera de operadores, 12 de los 16 pares
    contestaban un conjunto en Postgres y MySQL y otro en SQLite. Ahora se rechaza. Encadenar a la
    IZQUIERDA —`a.union(b).except_(c)`— es lo que el texto pelado ya significa y corre igual en los tres.

!!! note "Una `recursive()` es rama solo en Postgres"

    `(SELECT ...) UNION (WITH RECURSIVE ...)` es de Postgres. SQLite contesta `near "WITH": syntax error`
    y MySQL el error 1064, así que los dos declaran ausente `Cap.CTE_IN_COMPOUND_BRANCH` y la emisión
    rechaza en vez de dejar que el driver se queje de un SQL que tú no escribiste. Lanza la recursión
    como consulta propia y combina las filas después.

## Recursivas (`WITH RECURSIVE`)

Para árboles y grafos:

```python
# every descendant of category 1, at any depth
descendants = SnakeQuery(Category).filter(Category.id == 1).recursive(
    on=(Category.parent_id, Category.id)
)
session.all(descendants)

# a graph that may bite its own tail: UNION instead of UNION ALL, and the walk stops on its own
reachable = SnakeQuery(Node).filter(Node.id == 20).recursive(
    on=(Node.parent_id, Node.id), distinct=True
)
```

La query es el **ancla** (de dónde parte) y `on` es el par de columnas que encadena cada nivel con el
anterior.

`distinct` elige el operador de conjunto que une cada paso con lo ya acumulado — la misma elección
que `union()` y `union_all()` te dan en el resto del ORM:

| `distinct` | operador | cuándo |
| --- | --- | --- |
| `False` (por defecto) | `UNION ALL` | un **árbol**: no tiene duplicados que quitar, y quitarlos costaría hashear todo lo acumulado en cada paso |
| `True` | `UNION` | un **grafo** que puede tener ciclos: la vuelta que repite no aporta nada, así que el paso vuelve vacío y el recorrido termina |

!!! danger "`limit()` no es la salida de un ciclo"

    Con `UNION ALL` un recorrido cíclico no termina nunca: cada vuelta produce filas que el motor
    cuenta como nuevas, el paso nunca vuelve vacío y la consulta se cuelga en vez de fallar. Un
    `limit()` acota lo que te VUELVE, no hasta dónde llega el motor — medido contra Postgres sobre un
    ciclo de tres filas, el mismo recorrido con `order_by()` y `LIMIT 3` no vuelve nunca, porque la
    ordenación tiene que producir todas las filas antes de poder emitir una.

    El ORM no puede decidirlo por ti: una clave ajena contra su propia tabla admite un ciclo
    perfectamente, así que si lo hay es un dato de tu dominio, no de tu esquema. Si no puedes
    descartarlos, pasa `distinct=True`.

!!! danger "Un ancla no lleva `include()`, y en SQLite tampoco `limit()` propio"

    Una consulta con `include(...)` se rechaza como ancla de un `recursive()` y como rama de un
    `union`/`except_`/`intersect` — los mismos dos sitios, pero por un motivo propio y no por el del
    candado. Las columnas de un CTE son las de la tabla y las de un conjunto son las de la
    proyección, así que la relación que trae el LEFT JOIN no tiene por dónde viajar: volvería sin
    cargar y en silencio. Recurre o compón SIN `include()` y carga las relaciones sobre las filas
    que te vuelvan.

    Un `limit()` o un `offset()` en el ancla es solo de Postgres y MySQL. SQLite rechaza los
    paréntesis alrededor del ancla, y sin ellos la cota leería el recorrido entero en vez del primer
    paso, así que allí la emisión lo rechaza. Acota el RESULTADO con `.limit()` sobre la recursión,
    que pregunta lo mismo en los tres.

## Bloqueo de filas

```python
SnakeQuery(Account).filter(Account.id == 7).for_update()
SnakeQuery(Account).for_update(nowait=True)       # fails instead of waiting
SnakeQuery(Account).for_update(skip_locked=True)  # skips the locked ones
```

Con los [niveles de aislamiento](transactions.es.md) son las dos mitades del control de concurrencia. En
un motor sin bloqueo de filas (SQLite) el ORM lo dice, no lo ignora.

!!! danger "Un candado no viaja con `include()`"

    `for_update()` junto a `include()` se rechaza, en voz alta. Los dos piden un SQL distinto —el
    candado es sobre las filas de UNA tabla e `include()` trae otra por LEFT JOIN— y bloquear todas
    las tablas del JOIN casi nunca es lo que alguien quiso decir. Primero el candado, luego la carga:

    ```python
    # First the lock, on its own query and nothing else
    account = session.first(SnakeQuery(Account).filter(Account.id == 7).for_update())

    # Then whatever you need loaded, in a second query WITHOUT the lock
    detail = session.first(SnakeQuery(Account).filter(Account.id == 7).include(Account.owner))
    ```

    El mismo rechazo cubre `union`/`except_`/`intersect` y el ancla de un `recursive()`: un conjunto
    no tiene filas de una tabla concreta que bloquear.

## SQL crudo

La escotilla, cuando el builder no llega:

```python
from decimal import Decimal

from snakeorm import SnakeRow, snake_row

@snake_row
class Summary(SnakeRow):
    region: str
    total: Decimal

rows = session.raw(
    "SELECT region, SUM(amount) AS total FROM sales WHERE sold_on > %s GROUP BY region",
    (cutoff,),
    into=Summary,
)
rows[0].total  # Decimal, typed
```

Sigue siendo **parametrizado**: los valores van aparte, nunca dentro del string. El marcador lo
escribes tú y depende del motor —`%s` en PostgreSQL y MySQL, `?` en SQLite— porque `raw()` le pasa la
cadena al driver tal cual.

## Procedimientos y funciones

```python
session.call("compute_totals", [2024], into=Summary)     # returns rows
session.execute_procedure("recalculate_everything", [])  # returns nothing
```

`call()` emite `SELECT * FROM name(...)` e hidrata las filas por posición en el `@snake_row` que
declares; `execute_procedure()` emite `CALL name(...)` y no devuelve nada. Los argumentos van
parametrizados, como en todo lo demás; el nombre es un identificador, así que no puede, y pasa por
una comprobación de su forma.

Esto es **SQL opaco**, y llega más lejos de lo que parece: aquí no se le pregunta nada al catálogo de
capacidades, así que no se comprueba ni que la rutina exista, ni que su forma case con tu
`@snake_row`, ni que el motor TENGA rutinas siquiera. En SQLite no hay ninguna que llamar —sus
funciones las registra el proceso que abre la conexión, así que no viven nunca en la base— y lo que
vuelve es el driver quejándose de un SQL que tú no escribiste: `no such table: compute_totals` con
`call()` y `near "CALL": syntax error` con `execute_procedure()`. En todo lo demás el ORM para el
plan antes de que el motor lo vea; la escotilla es el único sitio donde la cadena es tuya y el error
también.

## Subconsultas escalares

Una subconsulta de una sola columna, para usarla dentro de `.in_(...)`:

```python
recent_buyers = (
    SnakeQuery(Order)
    .filter(Order.date_ > cutoff)
    .as_scalar(Order.customer_id)
)

SnakeQuery(Customer).filter(Customer.id.in_(recent_buyers))
```

Solo ahí: el resultado no es un valor comparable, y no lleva ni `order_by()` ni `limit()`. Una
columna directa y un `WHERE` plano; navegar una relación dentro se rechaza con todas las letras.

Tampoco se lleva nada de la consulta que ENVUELVE, y esa parte es callada: `as_scalar()` se queda
con la tabla, la columna y el `WHERE`, así que un `order_by()`, un `limit()`, un `offset()` o un
`distinct()` de la consulta envuelta se tiran y el SQL sale igual que si no los hubieras escrito.

Con `order_by()` y `distinct()` es honesto: un conjunto es el mismo ordenado o no, y el `IN` pregunta
por un conjunto. Con `limit()` y `offset()` no lo es — una página de filas es otra pregunta distinta
de todas ellas, y aquí esa pregunta desaparece en vez de rechazarse. Si quieres las primeras filas,
lanza esa consulta, coge los valores y filtra por ellos.

## IN compuesto

Filtrar por una TUPLA de columnas, que en SQL es `(warehouse_id, product_id) IN ((7, 3), (9, 1))`:

```python
snake_keys(Stock).in_([
    snake_key(Stock).set(Stock.warehouse_id, 7).set(Stock.product_id, 3),
    snake_key(Stock).set(Stock.warehouse_id, 9).set(Stock.product_id, 1),
])
```

Un `in_()` por columna es OTRA pregunta:
`Stock.warehouse_id.in_([7, 9]) & Stock.product_id.in_([3, 1])` es el producto cartesiano, y
contesta también `(7, 1)` y `(9, 3)`. Con pocas filas los dos se parecen.

Cada columna va emparejada con su valor en vez de ser posicional, y eso es lo que hace útil aquí al
comprobador de tipos: el hueco fija el tipo, así que un valor equivocado se rechaza en la columna
contra la que se puso. Una tupla posicional de dos enteros no le da al comprobador nada que cuadrar,
así que un par intercambiado pasa y vuelve mal. Tampoco hay límite de anchura — no hay sobrecargas
por medio, así que una clave de seis columnas se escribe igual que una de dos.

El hueco admite cualquier expresión escalar, no solo una columna pelada, y las columnas no tienen
por qué ser clave:

```python
from snakeorm.expressions import snake_upper

snake_keys(Stock).in_([
    snake_key(Stock).set(snake_upper(Stock.city), "BILBAO").set(Stock.units, 4),
])
```

Ese import va escrito porque es el que un lector falla: `snake_key`, `snake_keys`, `snake_case` y
`snake_coalesce` los reexporta el paquete raíz, y las funciones de cadena —`snake_upper`,
`snake_lower`, `snake_concat`— no. `from snakeorm import snake_upper` es un `ImportError`.

El orden en que encadenes es cosa tuya; la lista de columnas emitida sigue el orden de declaración
del modelo, así que dos claves encadenadas distinto producen el mismo SQL.

Lo que el sistema de tipos no puede comprobar es cuántos huecos tiene una clave —una de dos columnas
y otra de tres son las dos `SnakeKey[Stock]`—, así que esos fallos revientan antes de emitir nada:
una clave vacía, la misma columna puesta dos veces, y claves de la misma lista que no presenten las
mismas columnas. Ese último es el fallo callado: dos claves de la misma anchura sobre columnas
distintas compararían los valores de cada fila contra las columnas de la primera, y dos enteros no
hacen protestar a ningún motor.

Los tres motores lo ejecutan, y los tres lo ejecutan COMO constructor de fila:
`(a, b) IN ((...), (...))`, sin más cambio que el entrecomillado y el marcador. El ORM guarda un
equivalente `(a = ? AND b = ?) OR (...)` para un dialecto que no declare `Cap.ROW_CONSTRUCTOR`, y
pregunta lo mismo — pero aquí todos lo declaran `Full()`, así que ese camino es una puerta por la que
no pasa ninguno de los motores soportados.

Hay un techo, y es el del motor: ver [límites](../reference/limits.es.md).

---

Siguiente: [transacciones](transactions.es.md).
