# Transacciones

```python
with SnakeSession(driver, dialect) as session:
    session.add(order)
    session.add(line)
    # commit on exit; rollback if anything raises
```

O a mano, cuando controlas el ciclo tú:

```python
session.add(order)
session.commit()
# session.rollback()
```

Cada método que ofrece la sesión está en [Sesiones](../reference/api/session.es.md).

## Savepoints

Para deshacer **parte** de una transacción sin perder el resto:

```python
with SnakeSession(driver, dialect) as session:
    session.add(order)

    try:
        with session.savepoint():
            session.add(doubtful_line)  # if this blows up...
    except SnakeError:
        pass  # ...the order stays alive

    session.commit()
```

Anidan, y los nombres los genera la sesión (`sp1`, `sp2`...).

## Niveles de aislamiento

```python
from snakeorm import SnakeIsolation

session.set_isolation(SnakeIsolation.SERIALIZABLE)
```

`READ_UNCOMMITTED`, `READ_COMMITTED`, `REPEATABLE_READ`, `SERIALIZABLE`. Con
[`for_update()`](advanced-queries.es.md#bloqueo-de-filas) son las dos mitades del control de
concurrencia.

Dos condiciones que imponen los motores: **llámalo antes de leer o escribir** (`SET TRANSACTION`
solo vale como primera sentencia) y **en SQLite no**, que no tiene niveles de aislamiento. Ahí la
llamada se rechaza con un `SnakeUnsupportedFeature` que dice por qué: SQLite no tiene
`SET TRANSACTION ISOLATION LEVEL`, un escritor cada vez ya hace serializables sus transacciones, y su
único botón —`PRAGMA read_uncommitted`— BAJA el aislamiento en vez de subirlo.

## Reintentar un conflicto de serialización

Con `SERIALIZABLE`, el motor aborta lo que no puede serializar. La respuesta correcta es **rehacer
la unidad de trabajo entera**:

```python
from snakeorm import with_retry

seat = with_retry(session, lambda s: reserve_seat(s, course_id))
```

`attempts=3` por defecto.

!!! info "Por qué recibe una función y no una sentencia"

    Cuando el motor aborta una transacción, queda **entera** inutilizable (*current transaction is
    aborted*). Reintentar la sentencia no arregla nada: hay que volver al principio con su
    `rollback` en medio. Por eso `with_retry` recibe la unidad de trabajo completa.

    Reconoce el conflicto transitorio en los tres motores. Cualquier otra cosa se lanza tal cual:
    repetir una violación de constraint repite el fallo, y podría duplicar efectos secundarios.

## Escrituras que preguntan qué pasó

```python
user, created = session.get_or_create(
    SnakeQuery(User).filter(User.email == "ana@x.com"),
    lambda: User(email="ana@x.com", nickname="ana"),
)
if created:
    send_welcome(user)
```

`upsert` escribe, pero no dice si creó o ya existía:

```python
session.upsert(
    user,
    on_conflict=[User.email],
    update=[User.nickname],
)
```

## Recargar desde la base

Tras un trigger o un default del servidor que cambió la fila por debajo:

```python
session.refresh(order)
```

## En producción: envolver el driver

```python
from snakeorm import LoggingDriver, PostgresDialect, PsycopgDriver, TimeoutDriver

dialect = PostgresDialect()

driver = PsycopgDriver.connect(dsn)
driver = LoggingDriver(driver, write=print)  # write(line: str)
driver = TimeoutDriver(driver, dialect, statement_timeout_ms=5000)
```

El orden importa: el logger va primero para que registre también lo que hagan los envoltorios de
encima. `TimeoutDriver` recibe el dialecto porque la sentencia de timeout es del motor — y en uno que
no la tiene (SQLite) **rechaza el envoltorio** en vez de fingir que limita.

### Los valores no van al log

`LoggingDriver` escribe la sentencia y el NÚMERO de parámetros, nunca los parámetros:

```
INSERT INTO users (email, pw) VALUES (%s, %s) -- params=<2 hidden> -> 1 row(s)
```

`write=print` manda eso al stdout del proceso, que en un contenedor es el agregador de logs. La
sentencia es segura por construcción —el ORM nunca interpola, así que no lleva nada del usuario— y
los valores son lo único que sí podría llevarlo. Para ver uno, nombra su posición (base 0):

```python
driver = LoggingDriver(driver, write=print, parameter_keys=frozenset({"0"}))
```

**No hay variable de entorno** para esto, y la omisión es la decisión: una variable de entorno es
justo el interruptor que alguien pulsa en producción sin querer. Es la misma política, escrita
igual, que el `parameter_keys` del exportador de `otel`.

Para pooling, mira [varias conexiones](../engines/multi-connection.es.md).

---

Siguiente: [señales y triggers](signals-and-triggers.es.md).
