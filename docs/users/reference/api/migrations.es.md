# Migraciones

Los ficheros de migración son **Python**, no YAML ni JSON, y no es una
elección de estilo: `python_type` es un tipo de Python, y serializarlo a JSON exigiría un registro
nombre↔tipo — un segundo sistema de tipos, peor. En `.py` es un import y una referencia.

Cada operación sabe aplicarse y sabe deshacerse. Lo que un motor no puede hacer se para en el PLAN,
con un motivo legible, en vez de a mitad de un despliegue.

!!! note "De dónde sale este texto"

    Todo lo que hay bajo los títulos se genera desde los docstrings del propio paquete, en cada
    build.

    Los títulos sí están escritos a mano, así que esta página puede quedarse atrás respecto al
    módulo — se había quedado, por siete operaciones. La lista que no puede quedarse atrás es la del
    propio módulo:

    ```bash
    rg -n '^class ' src/snakeorm/migration/operations.py
    ```

## Runners

Una migración declara detrás de QUÉ va, y el cargador convierte esas declaraciones en un solo orden entre paquetes. Un ciclo se rechaza en voz alta, nombrando las migraciones que lo cierran — elegir un orden y confiar es lo único que no hace.

```python
from snakeorm.migration import Migration

class AddOrderTotals(Migration):
    """A migration from another package can be named as a dependency."""

    depends_on = ["billing.0003_add_plans"]
    operations = [...]
```

::: snakeorm.migration.Migration

::: snakeorm.migration.MigrationRunner

::: snakeorm.migration.AsyncMigrationRunner

## Autodetección

::: snakeorm.migration.autodetect

::: snakeorm.migration.replay

::: snakeorm.migration.diff_schema

::: snakeorm.migration.render_migration

::: snakeorm.migration.load

::: snakeorm.migration.drop_order

## Esquemas

::: snakeorm.migration.CreateSchema

::: snakeorm.migration.DropSchema

## Operaciones de tabla

::: snakeorm.migration.CreateTable

::: snakeorm.migration.DropTable

::: snakeorm.migration.RenameTable

::: snakeorm.migration.RebuildTable

::: snakeorm.migration.AlterTableComment

::: snakeorm.migration.AddColumn

::: snakeorm.migration.DropColumn

::: snakeorm.migration.RenameColumn

::: snakeorm.migration.AlterColumn

`RebuildTable` lleva una tabla de una forma de CONSTRAINTS a otra, y ahí está la salida de SQLite: no
tiene `ALTER TABLE ADD/DROP CONSTRAINT` ni lo tendrá, así que un CHECK o una clave ajena sobre una
tabla que YA EXISTE solo puede llegar rehaciendo la tabla a su alrededor — crear la nueva, copiar las
filas, tirar la vieja, renombrar. La operación no nombra ningún motor: Postgres y MySQL reciben el
`ALTER TABLE ... ADD CONSTRAINT` mínimo y solo, SQLite recibe la reconstrucción entera.

Recibe dos snapshots `SnakeTableInfo` ENTEROS, más los triggers que cuelgan de la tabla — la
reconstrucción se los lleva con ella y se los debe de vuelta. Y RECHAZA un par que discrepe en algo
que no sean CHECK y claves ajenas, nombrando lo que discrepa: una diferencia en columnas se aplicaría
en SQLite (que recrea la tabla desde `after`) y no en Postgres (cuyo `ALTER` mínimo no emite nada
para eso), dejando a los dos motores con esquemas distintos y a ninguno diciendo nada. Las columnas
tienen sus propias operaciones, y tirar una que sujeta una clave ajena NO es esta operación: SQLite
tampoco tiene `DROP CONSTRAINT` para quitar la clave de en medio antes, así que eso es un `RunSQL`
escrito a mano, y es decisión del usuario — ver [límites conocidos](../limits.es.md).

```python
from dataclasses import replace

from snakeorm.metadata import (
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRelationshipKind,
    SnakeTableInfo,
)
from snakeorm.migration import RebuildTable

tag_id = SnakeColumnInfo(name="id", python_type=int, attr_name="id", autoincrement=True)
parent_id = SnakeColumnInfo(
    name="parent_id", python_type=int, nullable=True, attr_name="parent_id"
)

# The WHOLE table as this migration finds it: on SQLite the rebuild recreates it from `after`, so
# anything left out of the snapshot is structure lost without a word.
tags = SnakeTableInfo(
    name="tags",
    columns=(tag_id, parent_id),
    primary_key=SnakePrimaryKeyInfo(columns=(tag_id,)),
)
parent = SnakeRelationshipInfo(
    name="parent",
    target="Tag",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="Tag", pairs=(("parent_id", "id"),)),
    target_table="public.tags",
)

operations = [
    RebuildTable(
        before=tags,
        after=replace(tags, relationships=(parent,)),
        triggers=(),
    ),
]
```

## Constraints e índices

::: snakeorm.migration.CreateIndex

::: snakeorm.migration.DropIndex

::: snakeorm.migration.AddCheck

::: snakeorm.migration.DropCheck

::: snakeorm.migration.AddForeignKey

::: snakeorm.migration.DropForeignKey

## Vistas, funciones y triggers

::: snakeorm.migration.CreateView

::: snakeorm.migration.DropView

::: snakeorm.migration.AlterView

::: snakeorm.migration.CreateFunction

::: snakeorm.migration.DropFunction

::: snakeorm.migration.AlterFunction

::: snakeorm.migration.CreateTrigger

::: snakeorm.migration.DropTrigger

::: snakeorm.migration.AlterTrigger

## Escotillas

::: snakeorm.migration.RunSQL

::: snakeorm.migration.RunPython

