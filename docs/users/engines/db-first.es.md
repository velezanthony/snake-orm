# DB-first y scaffolding

El scaffolder **traduce una base de datos viva a modelos**. Le apuntas a cualquier esquema —uno que
gobierna un DBA, uno que pertenece a otro repositorio, uno con el que tiene que hablar una función
serverless— y lo que sale consulta con la misma API tipada que un modelo escrito a mano, bajo
Django, FastAPI o Flask, o bajo Python pelado sin framework ninguno. Nada que cablear: conectas,
generas, consultas.

```bash
uv run snakeorm scaffold create --out app/models_legacy.py --schema public
uv run snakeorm scaffold update --out app/models_legacy.py     # rewrites it whole
```

- `create` falla si el fichero ya existe.
- `update` lo **sobrescribe entero**: es un espejo de la base, no conserva tus ediciones.

## Qué genera

```python
from __future__ import annotations

from snakeorm import (
    SnakeColumn, SnakeIndex, SnakeModel, SnakeToMany, SnakeToOne,
    snake_auto, snake_db_first, snake_int, snake_link, snake_str,
    snake_to_many, snake_to_one,
)

@snake_db_first(table="countries")
class PublicCountries(SnakeModel):
    """Mirror of table `countries`."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    customers_legacy: SnakeToMany[PublicCustomersLegacy] = snake_to_many("country")


@snake_db_first(table="customers_legacy")
class PublicCustomersLegacy(SnakeModel):
    """Mirror of table `customers_legacy`."""

    SnakeComment = "Customers imported from the 2011 system"

    id: SnakeColumn[int] = snake_auto()
    razon_social: SnakeColumn[str] = snake_str()
    nif: SnakeColumn[str | None] = snake_str(unique=True)
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[PublicCountries] = snake_to_one(country_id)

    SnakeIndexes = [
        SnakeIndex(country_id),
    ]

snake_link()
```

Un `@snake_db_first` es un modelo **completo**: consulta, inserta, actualiza y borra como cualquier
otro. La única diferencia: **las migraciones lo ignoran** — la fuente de verdad de su esquema es la
base, no el código.

**Las claves ajenas también vienen**, y la relación se llama como la COLUMNA local sin su `_id`
—`country_id` pasa a `country`—, que es la convención que guarda un modelo escrito a mano. Una clave
compuesta toma el prefijo que comparten sus columnas. Donde hay alguna relación que enlazar, el
fichero acaba en `snake_link()`; donde el esquema no tiene ni una clave ajena, no aparece ni la
llamada ni su import, porque no habría nada que resolver. El compilador es de dos fases, y un espejo
que declara relaciones sin enlazarlas importa limpio y revienta en la primera consulta.

**La relación dice lo mismo que su clave sobre el NULL.** Una clave ajena que acepta NULL sale como
`SnakeToOne[X | None]` y una `NOT NULL` no, porque el linker exige esa paridad en las dos
direcciones: con una clave nula, `include()` no encuentra pareja y cuelga un `None` de la relación,
así que un tipo no opcional sería una mentira que el checker aprueba.

**El lado inverso también se genera**, y la colección se llama como la TABLA hija, tal cual:
`customers_legacy` en `PublicCountries`. Eso TRANSCRIBE un token que la base ya tiene en vez de
inventarlo, que es toda la diferencia con un pluralizador — `status` → `Statu` es un nombre
equivocado que compila y que nada detecta. Donde una persona habría escrito `customers`, el espejo
te da `customers_legacy`: sin abreviar, no equivocado.

La regla es TOTAL, así que sus únicos fallos son colisiones, y las reporta todas en vez de emitir: un
nombre que ya ocupa una columna o una to-one, y la que no tiene respuesta — dos claves ajenas de la
misma tabla hija apuntando al mismo padre, donde nada en la base dice cuál colección es `sent` y cuál
`received`.

## No hay adopción in situ

Cambiar el decorador **no** le entrega los mandos a las migraciones, y esta página decía que sí:

```python
# This does NOT work against the database the mirror came from:
@snake_model(table="customers_legacy")   # was: @snake_db_first
class PublicCustomersLegacy(SnakeModel):
    ...
# makemigrations emits CreateTable -> DuplicateTable, because the history never knew the table.
```

El histórico de migraciones no tiene constancia de esa tabla, así que el autogen no tiene contra qué
comparar y emite un `CreateTable` — que muere contra una tabla que ya está. No hay `--fake` ni fila
de baseline que insertar: este ORM no la ofrece.

**Para lo que SÍ sirve el espejo** es para llevarse un esquema a OTRA base, gobernada desde cero.
Allí le quitas el decorador y el `CreateTable` que emite el autogen es exactamente lo correcto. La
base original se queda intacta, que es el sentido de todo esto: db-first significa que el esquema es
del sysadmin y este ORM es un cliente.

!!! info "Una FK hacia un modelo espejo SÍ se emite"

    Si un modelo gestionado apunta a uno no gestionado de la **misma** base, la constraint se crea:
    la tabla existe, solo que no la creaste tú. Entre bases distintas aplica la guarda de
    [varias bases de datos](multi-connection.es.md).

## Nombres de las clases

La clase se llama como la **tabla**, en CapWords y con el **esquema delante**, `public` incluido:

| tabla | clase |
|---|---|
| `public.project_requests` | `PublicProjectRequests` |
| `sales.orders` | `SalesOrders` |
| `public.ProductReQuests` | `PublicProductReQuests` |

**El plural se deja en paz**, y ésa es la decisión que importa. Quitar la `-s` final es adivinar en
inglés: convierte `status` en `Statu`, `analysis` en `Analysi` y `direcciones` en `Direccione`, y en
castellano acierta solo por casualidad. Partir por `_` y capitalizar no sabe de idiomas y no pierde
nada, así que esa mitad se queda.

**El esquema no tiene excepción.** `sales.orders` junto a `hr.orders` es lo normal, y sin prefijo son
una sola clase — el espejo se quedaría con la última y no lo diría.

Dos flags apagan cada mitad:

```bash
snakeorm scaffold create --out models.py --keep-underscores   # Public_project_requests
snakeorm scaffold create --out models.py --no-schema-prefix   # ProjectRequests
```

Quitar el prefijo no esconde lo que evitaba: las tablas que colapsan en una sola clase se avisan por
nombre.

**Lo que no se puede nombrar no se inventa nunca.** Una tabla o columna cuyo nombre no sea un
identificador ASCII —acentos, otro alfabeto, una palabra reservada de Python— se deja fuera y se
avisa, en el fichero y por consola. Un nombre adivinado es un espejo apuntando a algo que nadie pidió.

## Lo que un espejo NO puede llevarse

Una base de datos es una **proyección con pérdida del código**. El scaffolder solo puede devolver lo
que el catálogo guarda, y todo lo de abajo vive en un `.py` —a menudo en otro repositorio— sin que
ninguna fila de ninguna tabla del sistema lo mencione. No es que el generador aún no lo haga: es que
no hay de dónde sacarlo.

| qué | qué guarda la base | qué se pierde |
|---|---|---|
| `snake_on` / señales | nada | el handler — es una función de Python |
| `snake_enum` | las etiquetas | la clase `StrEnum`, los NOMBRES de sus miembros, sus métodos |
| `default_factory=` | nada | `datetime.now`, `uuid4`: se calculan en el cliente y nunca llegan al DDL |
| constantes del dominio | nada | viven en un módulo, no en una tabla |
| métodos, propiedades, docstrings | nada | la mitad de un modelo que no es una columna |
| el nombre que eligió una persona | el nombre de la TABLA | `User.sessions` por `login_sessions` es una abreviatura humana |
| `snake_discriminator` | una columna cualquiera | que ESA columna marque un subtipo |
| `snake_trigger` / `snake_function` | el cuerpo, en PL/pgSQL | nada que quepa en un `.py` sin copiar otro lenguaje |

`default=` SÍ vuelve, y la línea cae justo ahí: `default=` es un **literal de DDL**, así que el
servidor lo guarda, mientras que `default_factory=` es un programa.

Dicho sin adornos: **no puedes tirar tus modelos escritos a mano, regenerarlos del espejo y seguir
donde estabas.** El espejo va en la otra dirección — hacia una base que no escribiste tú.

## El round-trip NO es biyectivo

`TEXT`, `VARCHAR(50)` y `CHAR(10)` vuelven **todos** como `str`. Un viaje código → base → código no
reproduce tu fichero original. Es **correcto**: el mapeo SQL→Python pierde información por definición.
En SQLite es más marcado aún — su sistema de tipos es de afinidades, no de tipos.

## Nada se tira en silencio

Lo que la base tenga y el ORM no sepa expresar —triggers, tipos exóticos, índices por expresión— sale
como **aviso por consola y comentario en el fichero generado**:

```python
# INTROSPECTION WARNINGS: this EXISTS in the database and the model does NOT
# represent it. It is still there and still acting; it just cannot be seen from here.
#   - trigger: tg_customers_audit on customers
#   - expression index: ix_customers_lower_tax_id
```

## Detección de deriva

```bash
uv run snakeorm check --database default
```

Compara el esquema **real** contra tus modelos y avisa si no cuadran. No es lo mismo que
`makemigrations --check`:

| Comando | Compara | Caza |
|---|---|---|
| `makemigrations --check` | Código ↔ **histórico** | "Se me olvidó generar la migración" |
| `check` | Código ↔ **base real** | "Alguien tocó la base a mano" |

Hacen falta los dos. Con un `@snake_db_first`, `check` sí lo mira: tu espejo puede haberse quedado
obsoleto.

---

Siguiente: [cómo funciona el tipado](../reference/typing.es.md).
