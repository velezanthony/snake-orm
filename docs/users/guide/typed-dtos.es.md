# DTOs tipados

Una aplicación dice la forma de una misma respuesta más de una vez: el dict que arma la vista, el
serializador del framework que tenga delante, la interfaz de TypeScript del otro lado. Nada las
compara, así que se separan — y la separación es silenciosa, porque cada una es válida por su cuenta.

El generador de DTOs reduce eso a **una sola declaración**. Dices qué modelo y qué campos; el CLI
escribe el `TypedDict` en tu propio fichero, a partir de la metadata compilada.

```bash
uv run snakeorm dto --file blog/dto.py --sync     # write them
uv run snakeorm dto --file blog/dto.py            # check only: exits 1 if anything drifted
```

## Lo que escribes tú

La declaración vive dentro del bloque `if TYPE_CHECKING:` del propio fichero, junto al import de los
modelos:

```python
from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from snakeorm.dto import snake_dto

    from blog.models import Author, Post

    snake_dto(Author, fields=[Author.id, Author.username], name="AuthorDto")
    snake_dto(Post, fields=[Post.id, Post.title, Post.author], name="PostCard")
```

Tres cosas: qué modelo, qué campos y cómo se llama la clase. El nombre es **obligatorio** — es lo que
se va a escribir.

## Lo que escribe el CLI

Dentro de una región marcada de ese mismo fichero, y en ningún otro sitio:

```python
# snakeorm-dto: begin generated block
class AuthorDto(TypedDict):
    id: int
    username: str


class PostCard(TypedDict):
    id: int
    title: str
    author: AuthorDto
# snakeorm-dto: end generated block
```

Todo lo que queda fuera de las dos líneas marcadoras es tuyo y no se toca jamás. La región se
regenera entera en cada pasada, que es lo que hace que una segunda no tenga nada que escribir.

## Por qué la declaración va dentro de `if TYPE_CHECKING:`

Tres propiedades a la vez, y hacen falta las tres:

| | |
| --- | --- |
| el checker valida cada path | `Post.tilte` no compila |
| en runtime no se ejecuta nada | el bloque no llega a ejecutarse |
| el módulo no cuesta nada de importar | no arrastra los modelos, ni el ORM |

Así que el fichero con tus DTOs es barato de importar desde una vista, y el ciclo de imports entre
`models.py` y `dto.py` no puede formarse — el import que lo cerraría no ocurre nunca.

Y el CLI **lee** ese bloque del fuente con `ast`; no importa jamás el fichero que va a reescribir. Lo
que sí importa es el módulo de modelos que ese fichero nombra, porque la metadata compilada es donde
viven los tipos y la nulabilidad — así que un fichero de DTOs que no importa no es problema de este
comando, pero un módulo de modelos que revienta al importar sí lo sigue siendo.

## Las tres formas de elegir campos

| escribes | significa |
| --- | --- |
| `snake_dto(Post, name="X")` | todas las columnas |
| `snake_dto(Post, fields=[...], name="X")` | exactamente ésas |
| `snake_dto(Post, exclude=[...], name="X")` | todas menos ésas |

Las dos juntas es un error: son dos respuestas a la misma pregunta y pueden discrepar.

**Para cualquier cosa que cruce la red, mejor `fields=`.** Una exclusión publica cada columna que se
añada después — que es la dirección que falla en abierto.

## Las relaciones se ANIDAN, no se expanden

`Post.author` se convierte en `author: AuthorDto`, no en las columnas del autor injertadas. Lees
`author` y sabes que va anidado, y su forma es otra declaración con nombre propio.

Una columna al otro lado de un to-one se escribe como el path y se nombra por él:

```python
snake_dto(Post, fields=[Post.id, Post.author.username], name="PostLine")
```

da `author_username: str`. El path entero está en el nombre a propósito: con solo el último paso,
`author.username` y `editor.username` serían los dos `username` y uno taparía al otro en silencio.

Si un modelo tiene más de una declaración, di cuál anidar:

```python
snake_dto(Post, fields=[Post.id, (Post.author, "AuthorCard")], name="PostCard")
```

No se elige nada por ti. Dos declaraciones sobre un modelo y ninguna regla para escoger producirían
una clase con buen aspecto describiendo la forma equivocada.

## La nulabilidad se acumula sobre el path ENTERO

`Post.editor.username` es `str | None` aunque `username` sea NOT NULL, porque un LEFT JOIN sobre un
`editor_id` nullable no devuelve nada de verdad. `Post.editor` es `AuthorDto | None` por exactamente
el mismo motivo.

Una colección nunca es opcional: `Post.comments` es `list[CommentDto]`, porque un padre sin hijos
recibe una lista vacía.

## Esto escribe la FORMA, nunca la consulta

Aquí nadie emite el `include(...)` que rellena una relación anidada, y es deliberado: un `include()`
escrito en tu fichero sería un segundo sitio diciendo lo que la declaración ya dice. Lo que pasa si
se te olvida es la promesa más vieja del ORM, no un agujero:

```text
SnakeRelationshipNotLoaded: Relation 'author' was not loaded.
Use .include(Post.author) in the query.
```

O sea que una declaración que anida `Post.author` describe una fila leída con `include(Post.author)`.
Mantén la pareja, y el ORM te avisa cuando no lo hagas.

**Hay una forma de tragarse ese aviso.** `SnakeRelationshipNotLoaded` hereda de `AttributeError`, así
que `hasattr(row, name)` contesta `False` y `getattr(row, name, None)` devuelve el valor por defecto
— las dos en silencio. Un serializador que recorre una forma se escribe con esa llamada exacta,
porque los nombres vienen de datos. Usa el `getattr` de dos argumentos, que es lo que hace el ORM por
dentro.

## El modo check es el porqué de todo esto

```text
$ snakeorm dto --file blog/dto.py
blog/dto.py: Would write 1 change(s).
  AuthorDto: added `country_id: int | None`
Run `snakeorm dto --sync` to write them, and read the diff: these classes live in your files.
```

Código de salida 1. Añade una columna al modelo y el build se pone rojo, en vez de publicarse la
columna sin que nadie lo haya decidido. Ésa es la mitad que hace seguro usar `exclude=` y «todas las
columnas».

## Lo que NO hace

- **Escribir tus imports.** Ni siquiera `TypedDict`. Editar el bloque de imports de alguien a ojo es
  una reclamación mayor sobre su fichero que rellenar una región que él marcó, y equivocarse
  significa que el fichero deja de importar. Te dice qué línea añadir.
- **Renombrar un campo.** `author_username` es mecánico.
- **Expandir una relación** en las columnas del modelo lejano.
- **Agregar nada.** Un `COUNT` no es una forma, es una consulta.

Ese último grupo es la razón de que esto encaje en el payload de una API —que es la forma del
modelo— y no en la fila de una plantilla, que renombra claves, aplana `None` a `""` y formatea
fechas. Eso es presentación, no serialización.

## No se exporta desde el paquete raíz

Se importa de `snakeorm.dto`. Es una herramienta joven, y el paquete raíz es superficie publicada con
una red de documentación alrededor.

---

Siguiente: [cómo funciona el tipado](../reference/typing.es.md).
