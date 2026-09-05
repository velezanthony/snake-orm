---
hide:
  - navigation
---

# SnakeORM

**Navegación profunda de relaciones completamente tipada en Python. Sin codegen. Sin plugin de
type-checker.**

```python
Truck.maker.nation.name == "España"  # SnakeExpr[str] -> SnakeCondition
```

Mypy, Pyright y Pylance lo saben. Y genera esto:

```sql
SELECT t0."id", t0."model", t0."maker_id" FROM "public"."trucks" AS t0
JOIN "public"."makers" AS t1  ON t0."maker_id" = t1."id"
JOIN "public"."nations" AS t2 ON t1."nation_id" = t2."id"
WHERE t2."name" = %s
```

En Django escribirías `filter(maker__nation__name="España")`: una cadena mágica que no autocompleta,
no se comprueba, y si renombras `nation` te enteras en producción.

La distribución es `snake-orm` y el paquete es `snakeorm`. La versión se fija porque es una beta:
un `pip install snake-orm` a secas no recoge una preliminar.

```bash
pip install snake-orm==0.1.0b1   # or: pip install --pre snake-orm
```

[Empezar en cinco minutos](users/getting-started/installation.es.md){ .md-button .md-button--primary }
[Cómo funciona el tipado](users/reference/typing.es.md){ .md-button }

---

## Un vistazo completo

```python
from snakeorm import (
    SnakeColumn, SnakeModel, SnakeQuery, SnakeSession, SnakeToOne,
    PostgresDialect, PsycopgDriver,
    snake_auto, snake_int, snake_link, snake_model, snake_str, snake_to_one,
)

@snake_model(table="brands")
class Brand(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(unique=True)

@snake_model(table="cars")
class Car(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    model: SnakeColumn[str] = snake_str()
    brand_id: SnakeColumn[int] = snake_int()
    brand: SnakeToOne[Brand] = snake_to_one(brand_id)

snake_link()

session = SnakeSession(PsycopgDriver.connect(dsn), PostgresDialect())
cars = session.all(
    SnakeQuery(Car).filter(Car.brand.name == "Seat").order_by(Car.model)
)
```

---

## La tesis

Un ORM moderno **puede** tener navegación profunda de relaciones totalmente tipada, sin generar
código y sin plugin de type-checker. **El sistema de tipos es la única fuente de verdad**; el runtime
solo ejecuta SQL sobre metadata ya compilada. Verificado con mypy **y** pyright: un test exige que
coincidan — [cómo funciona](users/reference/typing.es.md).

---

## Qué trae

<div class="grid cards" markdown>

-   :material-key-variant:{ .lg .middle } **Tipado que no miente**

    ---

    Relaciones profundas, agregados, proyecciones y enumerados devuelven su tipo real. Cero `Any`,
    verificado con `--strict`.

    [:octicons-arrow-right-24: Cómo funciona](users/reference/typing.es.md)

-   :material-database-sync:{ .lg .middle } **Migraciones con autogen**

    ---

    Diff del modelo contra el histórico, ficheros legibles y reversibles, squash y detección de
    deriva contra la base real.

    [:octicons-arrow-right-24: Migraciones](users/getting-started/migrations.es.md)

-   :material-swap-horizontal:{ .lg .middle } **Tres motores, una metadata**

    ---

    PostgreSQL, MySQL/MariaDB y SQLite. El modelo es 100% agnóstico: el motor solo entra al emitir y
    al ejecutar.

    [:octicons-arrow-right-24: Dialectos](users/engines/dialects.es.md)

-   :material-lightning-bolt:{ .lg .middle } **Síncrono y asíncrono**

    ---

    La generación de SQL no tiene color, así que `AsyncSession` reutiliza el núcleo entero. Paridad
    comprobada por la máquina.

    [:octicons-arrow-right-24: Asíncrono](users/engines/async.es.md)

</div>

---

## Principios

- **Nada falla en silencio.** Cuando algo no se puede hacer, se dice; cuando se puede traducir, se
  traduce; cuando la herramienta no sabe decidir, para y pregunta.
- **El tipo viene de Python.** `SnakeColumn[str | None]` es nulable porque lo dice la anotación, no
  un `nullable=True` que pueda contradecirla.
- **Cada límite está escrito.** La página de [límites conocidos](users/reference/limits.es.md) es parte
  del contrato, no una lista de disculpas.
