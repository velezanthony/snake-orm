# Tu primer modelo

Un modelo es una clase con descriptores tipados. Sin metaclase, sin campo mágico.

```python
from snakeorm import SnakeColumn, SnakeModel, snake_auto, snake_column, snake_model, snake_str

@snake_model(table="users")
class User(SnakeModel):
    id: SnakeColumn[int] = snake_auto()
    email: SnakeColumn[str] = snake_str(unique=True)
    nickname: SnakeColumn[str | None] = snake_str()
    active: SnakeColumn[bool] = snake_column(default=True)
```

Genera:

```sql
CREATE TABLE "public"."users" (
  "id" BIGSERIAL,
  "email" TEXT NOT NULL,
  "nickname" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY ("id"),
  CONSTRAINT "uq_users_email" UNIQUE ("email")
)
```

## Tres cosas que entender

### 1. El tipo lo dice la anotación, y solo la anotación

`nickname: SnakeColumn[str | None]` es nulable porque el `| None` está ahí. No existe `nullable=True`:
dos fuentes para el mismo dato significan que una puede mentir.

El resto sale igual. En PostgreSQL: `int` → `BIGINT`, `Decimal` → `NUMERIC`, `dict` → `JSONB`,
`UUID` → `UUID`; y `datetime` → `TIMESTAMP` mientras que `SnakeUtc` → `TIMESTAMPTZ`, porque una hora
de pared y un instante son dos tipos de columna distintos y es la anotación la que dice cuál. La
metadata solo añade info de SQL (unicidad, defaults), nunca el tipo.

La tabla completa — cada tipo, contra los tres motores — está en
[columnas y tipos](../guide/columns.es.md#tipos-soportados), y solo ahí. Una tabla copiada en una
segunda página es una tabla que se desincroniza, y ésta ya lo hizo.

### 2. `snake_auto()` no es un argumento del constructor

```python
user = User(email="ana@x.com", nickname=None)  # no `id`
```

La PK autoincremental la pone la base, así que se **excluye** del `__init__`. Tras el `INSERT`, el
valor aparece (vino en el `RETURNING`):

```python
session.add(user)
user.id  # there it is
```

### 3. Se imprime y se compara como esperas

```pycon
>>> user
User(id=7, email='ana@x.com', nickname=None, active=True)
```

La igualdad va por **clave primaria**, no por valor. Las PK compuestas usan el mismo código, sin
caso especial.

!!! warning "Hashear un objeto sin PK lanza `TypeError`"

    A propósito. Si el hash saliera de una PK vacía, el `INSERT` la rellenaría después y mutaría el
    hash de un objeto ya metido en un `set`. Insértalo primero.

## Nombres de tabla

```text
@snake_model                                   # table: "users" (class name + s)
@snake_model(table="users_legacy")          # table: "users_legacy"
@snake_model(prefix="app", table="users")   # table: "app_users"
@snake_model(schema="analytics")               # table: "analytics"."users"
```

!!! note "La pluralización por defecto es ingenua"

    `f"{ClassName.lower()}s"`. `User` → `users`, pero `Country` → `countrys`. Para plurales reales
    usa `table="..."`.

## Bases abstractas

Columnas compartidas (auditoría, típicamente) sin que la base sea una tabla:

```python
from snakeorm import SnakeUtc, snake_abstract, snake_datetimetz

@snake_abstract
class WithAudit(SnakeModel):
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)

@snake_model(table="orders")
class Order(WithAudit):
    id: SnakeColumn[int] = snake_auto()
```

`WithAudit` aporta sus columnas a cada tabla hija y no genera ninguna propia. Consultarla lanza un
error explícito.

Para las otras formas de herencia —duplicar columnas en tablas hermanas, o compartir tabla con un
discriminador— mira [herencia](../guide/inheritance.es.md).

---

Siguiente: [consultar](querying.es.md).
