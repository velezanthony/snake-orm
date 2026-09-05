# Cómo funciona el tipado

Cómo puede `Car.brand.country.name` estar tipado sin codegen ni plugin. La respuesta cabe en una
idea: **descriptores con `__get__` sobrecargado**.

## El problema

El mismo nombre significa **dos cosas** según desde dónde se mire:

```python
car.brand  # instance -> the Brand object       -> Brand
Car.brand  # class    -> something to filter with
```

Django lo resuelve con strings (`filter(brand__country__name="x")`), y por eso ningún checker ayuda.

## La solución

Un descriptor recibe la instancia en `__get__`. Si es `None`, el acceso es **de clase**. Se
sobrecarga el retorno según ese caso:

```python
class SnakeColumn(Generic[T]):
    @overload
    def __get__(self, instance: None, owner: type) -> SnakeExpr[T]: ...
    @overload
    def __get__(self, instance: object, owner: type) -> T: ...
```

```python
car.price  # -> Decimal
Car.price  # -> SnakeExpr[Decimal]
```

## La recursión

Para relaciones, el acceso de clase devuelve `type[M]`:

```python
class SnakeToOne(Generic[M]):
    @overload
    def __get__(self, instance: None, owner: type) -> type[M]: ...
    @overload
    def __get__(self, instance: object, owner: type) -> M: ...
```

1. `Car.brand` → `type[Brand]`
2. `.country` sobre `type[Brand]` es **otro acceso de clase** → `type[Country]`
3. `.name` sobre `type[Country]` → `SnakeExpr[str]`, y `== "x"` → `SnakeCondition`

La cadena entera queda tipada a cualquier profundidad, sin código escrito para el nivel tres. Es el
*mapped type* de TypeScript, hecho a mano con lo que Python sí tiene.

## El constructor

`@dataclass_transform` (PEP 681) le dice al checker que el decorador se comporta como `@dataclass`.
Los *field specifiers* declaran qué campos entran en el `__init__`:

```python
@dataclass_transform(
    kw_only_default=True,
    field_specifiers=(
        snake_column, snake_auto, snake_enum,
        snake_int, snake_str, snake_decimal, snake_datetime, snake_datetimetz,
        snake_float, snake_time, snake_timetz, snake_json,
        snake_to_one, snake_to_many, snake_to_many_through, snake_discriminator,
    ),
)
def snake_model(cls=None, *, table=None, prefix=None, schema="public",
                database="default", discriminator_value=None, registry=default_registry): ...
```

Un especificador con `init: Literal[False]` **excluye** su campo: por eso `User(email="...")` no
exige el `id` autoincremental ni el discriminador.

!!! danger "La tupla tiene que ser LITERAL (PEP 681)"

    No se puede extraer a una constante — mypy lo rechaza. Así que la misma tupla vive en cinco
    sitios, y olvidar uno deja de tipar ese camino **en silencio**. Un test lee el
    `__dataclass_transform__` de los cinco en runtime y exige que coincidan.

## Los bordes afilados

- **`type[Brand]` es "llamable"**: el checker permite `Car.brand()`. No hace nada; no hay forma de
  prohibirlo.
- **`SnakeExpr.__eq__` devuelve `SnakeCondition`, no `bool`** — lo que hace posible
  `filter(Car.price == 100)`. Consecuencia: `SnakeValue.__hash__` es `None` a propósito.
- **`assert Car.price == 100` siempre pasa**: `SnakeCondition` es *truthy*. Es el precio de la
  sobrecarga.

## La verificación

Mypy y pyright **deben coincidir**. En `test/typing/`: `cases_positive.py` (lo que debe compilar) y
`cases_negative.py` (lo que no, cada caso marcado con `# EXPECT: <error-code>` y el código de
**mypy** — `attr-defined`, `union-attr`, `call-overload` y los demás que el fichero provoca). El
marcador es lo que hace del fichero un contrato y no un montón de líneas rotas: el test exige ESE
error en ESA línea y ningún error en ninguna otra, así que un refactor que abra un agujero hace
desaparecer el error, la línea deja de casar y el test se pone rojo.

Los dos checkers corren sobre los mismos ficheros, y lo que se compara entre ellos son las **líneas**,
no los códigos: pyright nombra los mismos errores de otra forma, así que exigir su redacción sería
fijar el vocabulario de un proveedor en vez del agujero en los tipos.

---

Siguiente: [arquitectura](../../contributors/architecture.es.md) o [límites conocidos](limits.es.md).
