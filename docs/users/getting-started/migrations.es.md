# Migraciones

Los modelos son la fuente de verdad. `makemigrations` compara lo que declaras contra el histórico y
genera un fichero con la diferencia.

```bash
uv run snakeorm makemigrations --models myapp.models   # writes migrations/0001_initial.py
uv run snakeorm migrate --models myapp.models          # applies them
uv run snakeorm status --models myapp.models           # which ones are applied
uv run snakeorm rollback --models myapp.models         # undoes the last one
```

## Usarlo desde un framework web

No hay nada que configurar. Lanza el comando desde tu proyecto y él encuentra la aplicación:

```bash
cd myproject        # where manage.py / main.py / app.py lives
uv run snakeorm tables
uv run snakeorm makemigrations --name add_notes
uv run snakeorm migrate
```

```python
# myproject/settings.py, main.py, app.py — wherever your entry point already is
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.contrib.config import SnakeOrmConfig

SNAKEORM = SnakeOrmConfig(
    databases={"default": SnakeConnectionConfig(backend=SnakeBackend.POSTGRES, name="mydb")},
    migrations_dir="migrations",
)
```

Funciona porque la aplicación ya dijo todo lo que el CLI necesita. `SnakeOrmConfig` vive en
`snakeorm.contrib.config`; no es un export de primer nivel. Importar ese módulo es además lo que
ejecuta los decoradores `@snake_model`. Así que el CLI busca el punto de entrada tal y como lo define
cada framework (`manage.py` y su `DJANGO_SETTINGS_MODULE`, `main.py`, `app.py`, `wsgi.py`), lo
importa, y saca la config **por tipo**. No hay ningún nombre que recordar ni un segundo fichero que
escribir.

Que el MOTOR salga de ahí también es lo que merece la pena notar: `snakeorm migrate` corre en SQLite
y en MySQL, no solo en Postgres, porque la config empareja driver y dialecto y el CLI ahora pregunta
en vez de suponer.

!!! tip "¿Prefieres el comando de tu framework? Se añade en una línea"

    El ejecutable funciona en todas partes y no necesita nada. Si prefieres teclear lo que tu
    framework te enseñó, los adaptadores no llevan lógica: pasan los argumentos al mismo CLI.

    ```python
    # myapp/management/commands/snakeorm.py      ->  manage.py snakeorm tables
    from snakeorm.cli.hooks import SnakeOrmCommand as Command
    ```

    ```python
    # your Flask factory                          ->  flask snakeorm tables
    from snakeorm.cli.hooks import flask_command

    app.cli.add_command(flask_command())
    ```

    FastAPI no tiene adaptador, y es deliberado: no tiene línea de comandos propia donde engancharse
    (`uvicorn main:app` es un argumento a otro programa), así que usa el ejecutable, que ya no
    necesita configuración.

!!! danger "Tu módulo de entrada tiene que poder importarse sin hacer trabajo"

    El CLI lo importa, y ese import es lo que registra los modelos. Un módulo que abre conexiones,
    migra o siembra al importarse hará todo eso porque pediste listar tus tablas. Los settings de
    Django son constantes y FastAPI mete sus efectos en `lifespan`; en Flask, deja que el CLI
    encuentre `create_app` en vez de llamarla tú al final del fichero — la misma disciplina que evita
    que `flask run --reload` resiembre en cada guardado. Si de verdad necesitas trabajar al importar,
    protégelo con la variable `SNAKEORM_CLI`, que se pone antes de importar.

!!! info "Los tres motores, en los tres ejes"

    Leer un esquema es el tercer eje junto a escribir el SQL y ejecutarlo, y ya tiene una
    implementación por motor como los otros dos. `scaffold` y `check` funcionan en PostgreSQL,
    MySQL/MariaDB y SQLite; el CLI elige la que corresponde a la conexión que declara tu aplicación,
    igual que elige el driver y el dialecto.

    ```bash
    snakeorm scaffold create --out mirror.py   # Postgres, MySQL/MariaDB or SQLite
    snakeorm check                             # drift: your models vs the real schema
    snakeorm fresh                             # wipe and rebuild from the migrations
    ```

    `fresh` también: vaciar un esquema es DDL, así que cada dialecto escribe el suyo —Postgres
    cascadea, MySQL rodea los drops con su interruptor de claves ajenas, SQLite con el pragma—.

    Lo que devuelve un espejo no es el inverso exacto de lo que se escribió; mira
    [db-first](../engines/db-first.es.md).

`status`, `tables`, `table` y `advise` completan el juego: qué migraciones están aplicadas, qué
declaran los modelos, una tabla en detalle, y qué claves ajenas no tienen índice.

### Cuando quieras decirlo tú

`--models` y `--dsn` mandan por encima del descubrimiento. `--models` es una ruta de import
(`myapp.models`, no `myapp/models.py`) y sigue siendo OBLIGATORIO en `makemigrations --only`, que es
el único sitio donde nombra algo que el descubrimiento no puede adivinar: QUÉ dominio lleva la
migración. `--database` elige una conexión por nombre cuando la config declara varias.

No todos los comandos aceptan todos los flags: `makemigrations` y `squash` no tienen `--dsn`.
Pregúntale a `snakeorm <comando> --help`.

Sin aplicación que encontrar y sin flags, el CLI se para y nombra las rutas que intentó. Nunca cae a
una base de datos que nadie nombró.

## Qué hay dentro de un fichero

Python normal y legible. No hay SQL congelado; por eso la misma migración vale para dos motores:

```python
from snakeorm.metadata import SnakeColumnInfo, SnakePrimaryKeyInfo, SnakeTableInfo
from snakeorm.migration import AddColumn, CreateTable

operations = [
    CreateTable(
        SnakeTableInfo(
            name="users",
            columns=(
                SnakeColumnInfo(name="id", python_type=int, autoincrement=True),
                SnakeColumnInfo(name="email", python_type=str, unique=True),
            ),
            primary_key=SnakePrimaryKeyInfo(columns=(...,)),
        )
    ),
]
```

Cada operación de ESQUEMA sabe tres cosas: su SQL de ida (`up_sql`), su SQL de vuelta (`down_sql`) y
cómo muta el estado abstracto (`apply_to_state`). La tercera es la que deja a `makemigrations`
reconstruir el esquema según el histórico **sin conectarse** a la base.

Una operación de DATOS es la otra forma, y `RunPython` —más abajo— es una: conserva
`apply_to_state` y cambia las dos mitades de SQL por `run` y `unrun`, porque no tiene SQL propio que
entregar: recibe una sesión y hace el trabajo ella misma. Su `apply_to_state` no hace nada, que es
la respuesta honesta: mover filas de sitio no cambia ninguna forma contra la que la siguiente
migración pueda diferenciar.

## Qué detecta el autogen

Tablas, columnas, tipos, nulabilidad, defaults, **índices**, constraints `UNIQUE` y `CHECK`, claves
foráneas (incluidos cambios de `on_delete`), esquemas, vistas, funciones y triggers.

## Renombrar una columna

El diff ve un `DROP` + un `ADD`, y aplicarlos **pierde los datos**. Cuando detecta el patrón, sugiere
por consola:

```
Warning: this could be a RENAME, and as it stands it DELETES the old column's data.
  - users: did you rename 'nickname' to 'nick'? Replace its DropColumn + AddColumn
    with RenameColumn(users, old_name="nickname", new_name="nick").
```

Sugiere; **no decide**. Adivinar un renombrado y equivocarse sería peor que preguntar.

## En CI

```bash
uv run snakeorm makemigrations --models myapp.models --check   # exits != 0 if a migration is missing
uv run snakeorm check --models myapp.models                    # code vs the real DATABASE
```

El primero caza "se me olvidó generar la migración" (código vs histórico). El segundo caza "alguien
tocó la base a mano" (código vs BD real). Hacen falta los dos.

## Colapsar el histórico

```bash
uv run snakeorm squash --until 0042 --name initial
```

Genera una migración que **sustituye** ese tramo:

| Situación | Qué hace |
|---|---|
| Ninguna sustituida aplicada | La ejecuta. Instalación nueva. |
| Todas aplicadas | La marca aplicada **sin ejecutarla**. La base ya está así. |
| Algunas sí y otras no | **Para y te lo dice.** |

El tercer caso no tiene respuesta que adivinar: ejecutar repetiría; marcar se saltaría lo que falta.
Las dos corrompen.

!!! warning "Al actualizar desde una versión anterior a los `type_params`"

    La metadata de columna cambió de forma: `int_size`, `max_length`, `json_storage`,
    `precision` y `scale` dejaron de ser campos sueltos de `SnakeColumnInfo` y viajan en un
    `type_params` tipado por familia. Los ficheros de migración **ya generados** los escriben con
    la forma vieja, así que **dejan de cargar**.

    No hay capa de compatibilidad, y es deliberado: un camino, sin legado. La salida es colapsar
    el histórico con el `squash` de arriba y regenerar. Si la base ya está al día, la migración
    resultante se marca aplicada sin ejecutar nada, así que no se toca ni un dato.

## Migraciones de datos

Para rellenar una columna nueva a partir de otra, DDL no basta:

```python
from snakeorm import SnakeQuery
from snakeorm.migration import AddColumn, RunPython

def fill(session):
    session.update_where(
        SnakeQuery(User).filter(User.nickname.is_null()),
        [(User.nickname, "")],
    )

def undo(session):
    ...

operations = [AddColumn(...), RunPython(fill, undo)]
```

`forward` y `backward` reciben una `SnakeSession` sobre la **misma** conexión y transacción, así que
una migración mixta (esquema + datos) sigue siendo todo-o-nada. Deben ser funciones a nivel de
módulo, no lambdas: el renderizador las escribe por referencia.

!!! warning "Sin `backward`, el rollback lanza un error explícito"

    Una migración de datos irreversible no se deshace sola. El error te dice exactamente qué añadir.

## Atomicidad

PostgreSQL y SQLite tienen DDL transaccional, así que cada migración es **todo o nada**. El ORM no lo
da por hecho: lo lee de `supports_transactional_ddl`. En un motor sin él (MySQL), el error dice
cuántas operaciones se aplicaron antes de fallar.

---

Siguiente: los [ejemplos ejecutables](examples.es.md) —la misma API impresa contra una base de datos de
verdad—, o directo a la [guía](../guide/columns.es.md), o a [dialectos](../engines/dialects.es.md) si te
interesa qué cambia entre motores.
