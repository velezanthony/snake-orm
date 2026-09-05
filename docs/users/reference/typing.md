# How typing works

How `Car.brand.country.name` can be typed without codegen or a plugin. The answer fits in one idea:
**descriptors with an overloaded `__get__`**.

## The problem

The same name means **two things** depending on where you look from:

```python
car.brand  # instance -> the Brand object       -> Brand
Car.brand  # class    -> something to filter with
```

Django solves it with strings (`filter(brand__country__name="x")`), and that's why no checker helps.

## The solution

A descriptor receives the instance in `__get__`. If it's `None`, the access is **class-level**. You
overload the return on that case:

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

## The recursion

For relations, the class access returns `type[M]`:

```python
class SnakeToOne(Generic[M]):
    @overload
    def __get__(self, instance: None, owner: type) -> type[M]: ...
    @overload
    def __get__(self, instance: object, owner: type) -> M: ...
```

1. `Car.brand` → `type[Brand]`
2. `.country` on `type[Brand]` is **another class access** → `type[Country]`
3. `.name` on `type[Country]` → `SnakeExpr[str]`, and `== "x"` → `SnakeCondition`

The whole chain is typed at any depth, with no code written for level three. It's TypeScript's
*mapped type*, built by hand with what Python does have.

## The constructor

`@dataclass_transform` (PEP 681) tells the checker the decorator behaves like `@dataclass`. The
*field specifiers* declare which fields go into the `__init__`:

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

A specifier with `init: Literal[False]` **excludes** its field: that's why `User(email="...")`
doesn't require the autoincrement `id` nor the discriminator.

!!! danger "The tuple has to be LITERAL (PEP 681)"

    It can't be extracted to a constant — mypy rejects it. So the same tuple lives in five places,
    and forgetting one stops typing that path **silently**. A test reads the
    `__dataclass_transform__` of all five at runtime and requires them to match.

## The sharp edges

- **`type[Brand]` is "callable"**: the checker allows `Car.brand()`. It does nothing; there's no
  way to forbid it.
- **`SnakeExpr.__eq__` returns `SnakeCondition`, not `bool`** — which is what makes
  `filter(Car.price == 100)` possible. Consequence: `SnakeValue.__hash__` is `None` on purpose.
- **`assert Car.price == 100` always passes**: `SnakeCondition` is *truthy*. It's the price of the
  overload.

## The verification

Mypy and pyright **must agree**. In `test/typing/`: `cases_positive.py` (what has to compile) and
`cases_negative.py` (what must not, each case marked `# EXPECT: <error-code>` with **mypy's** code —
`attr-defined`, `union-attr`, `call-overload` and the rest of the ones the file provokes). The marker
is what makes the file a contract rather than a pile of broken lines: the test demands THAT error on
THAT line and no error on any other, so a refactor that opens a hole makes the error vanish, the line
stop matching and the test go red.

Both checkers run over the same files, and what is compared between them is the **lines**, not the
codes: pyright names the same mistakes differently, so demanding its wording would be pinning a
vendor's vocabulary instead of the hole in the types.

---

Next: [architecture](../../contributors/architecture.md) or [known limits](limits.md).
