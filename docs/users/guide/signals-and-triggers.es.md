# Señales y triggers

```python
from snakeorm import SnakeSignal, snake_on

@snake_on(Order, SnakeSignal.POST_SAVE)
def notify(order: Order) -> None:
    send_email(order.customer_email)
```

Dos mecanismos distintos, en dos sitios distintos. La regla: si es una **regla de datos**, va en un
trigger de base de datos; si es un **efecto de aplicación**, va en una señal de código.

| | Señales de código | Triggers de base de datos |
|---|---|---|
| Dónde corre | En tu proceso Python | Dentro del motor |
| Qué escrituras ve | Solo las del ORM | **Todas**, vengan de donde vengan |
| Qué puede hacer | Cualquier cosa (email, encolar job) | Solo lo que la base permita |
| Escritura masiva | No la ve | Sí la ve |
| Migraciones | No aplica | Se versionan como cualquier objeto |

## Señales de código

Cuatro momentos: `PRE_SAVE`, `POST_SAVE`, `PRE_DELETE`, `POST_DELETE`. El handler recibe la
**instancia**, tipada (ejemplo arriba).

!!! warning "Un handler que lanza se lleva la escritura — si hay transacción"

    Las excepciones no se capturan, a propósito: tragárselas dejaría datos guardados a medias sin que
    nadie se entere. Pero quien DESHACE la escritura es la transacción, no la señal: el
    `with SnakeSession(...)` hace rollback al salir. Fuera de uno, la excepción te llega y lo que ya
    estuviera confirmado sigue confirmado. La señal es la alarma; el `with` es la red.

!!! danger "La escritura masiva NO dispara señales"

    ```python
    session.update_where(SnakeQuery(Order).filter(Order.id > 0), [(Order.status, "closed")])
    session.delete_where(SnakeQuery(Order).filter(Order.id > 0))
    ```

    Cada una es UNA sentencia SQL: no hay instancias que notificar, y cargarlas sería N+1. Tanto
    `update_where` como `delete_where` te **avisan** si el modelo tiene señales registradas. Si las
    necesitas, itera con `session.update(instance)` / `session.delete(instance)`.

## Triggers de base de datos

Se declaran como metadata, entran en el diff y viajan en las migraciones igual que una tabla:

!!! warning "Casi toda esta sección es solo PostgreSQL"

    El cuerpo de un trigger es SQL del motor, así que el ORM lo transporta en vez de traducirlo. Tres
    cosas que saber antes de copiar el ejemplo de abajo:

    - **`snake_function` es solo PostgreSQL.** `Cap.STORED_FUNCTIONS` es `Nope` en MySQL/MariaDB y en
      SQLite, así que una migración que cree una se rechaza en los dos, por su nombre.
    - **`events=[INSERT, UPDATE]` en un mismo trigger es gramática de PostgreSQL.** El emisor los une
      con `OR`, y MySQL y SQLite lo rechazan.
    - **`TRUNCATE` con el `for_each_row=True` por defecto lo rechaza el propio PostgreSQL**: un
      trigger de truncado es de sentencia. Pasa `for_each_row=False`.


```python
from snakeorm import SnakeTriggerEvent, SnakeTriggerTiming, snake_function, snake_trigger

snake_function(
    name="stamp_modified",
    body="""
    CREATE OR REPLACE FUNCTION stamp_modified() RETURNS trigger AS $$
    BEGIN
        NEW.modified_at := now();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
)

snake_trigger(
    name="tg_orders_stamp",
    table="orders",
    timing=SnakeTriggerTiming.BEFORE,
    events=[SnakeTriggerEvent.INSERT, SnakeTriggerEvent.UPDATE],
    body="EXECUTE FUNCTION stamp_modified()",
)
```

El cuerpo es **opaco**: el ORM no lo interpreta, solo lo versiona y genera la migración cuando cambia.
No hay builder de PL/pgSQL, a propósito.

Escribe el cuerpo con `CREATE OR REPLACE`: el ORM lo emite tal cual tanto al crear como al cambiar,
así que un `CREATE FUNCTION` pelado falla la segunda vez con *function already exists*.

El resto del catálogo:

| Argumento | Valores |
|---|---|
| `timing` | `BEFORE`, `AFTER`, `INSTEAD_OF` |
| `events` | `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` |
| `for_each_row` | `True` por defecto (trigger de fila); `False` para trigger de sentencia |
| `schema` | `"public"` por defecto |

## Cuál elegir

- Sellar `modified_at` → **trigger**. Vale para toda escritura.
- Contador desnormalizado → **trigger**. Es una regla de datos.
- Email de bienvenida → **señal**. La base no manda emails.
- Invalidar una caché de tu app → **señal**. La base no sabe qué es tu caché.
- Auditar quién cambió qué → **trigger** si es "todo el mundo"; **señal** si solo importa lo que pasa
  por la aplicación.

---

Siguiente: [dialectos](../engines/dialects.es.md).
