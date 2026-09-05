# SnakeORM benchmarks

Un banco de pruebas **básico y autocontenido** que mide las operaciones propias de SnakeORM contra un
PostgreSQL de verdad e imprime una tabla de tiempos. Es una **línea base nuestra**, no un ranking.

## Qué mide

Siete benchmarks, cada uno sobre el esquema propio del banco (tablas `bench_*`, clases `Bench*`):

1. **Compilación (una vez)** — compilar los modelos + `snake_link()`, repetido. Mide la tesis del
   proyecto: «compilar una vez» sale barato porque la metadata se calcula UNA sola vez.
2. **Emisión de SQL (sin BD)** — `query.to_sql(dialect)` de una consulta PROFUNDA (3 JOINs) repetida
   N veces. Mide el coste de generar SQL desde el AST ya compilado (tiene que ser rápido, sin tocar
   la BD).
3. **INSERT** — `add_all` de lotes grandes (1.000 y 10.000 filas por defecto); tiempo total y
   filas/segundo.
4. **SELECT simple** — traer N filas con `session.all(...)`, incluido el mapeo a instancias.
5. **SELECT con navegación profunda** — filtrar por una cadena de 3 saltos (`BenchTruck.maker.nation.
   continent.name`); tiempo de ejecución + mapeo.
6. **include to-many (select-in)** — cargar N padres con sus hijos. Envuelve el driver en un contador
   y demuestra que se emiten **2 consultas** (1 raíz + 1 select-in), NO N+1.
7. **annotate / agregados** — `COUNT` + `AVG` de los hijos por padre, agrupando por la PK.

Todos los tiempos usan `time.perf_counter()`. Antes de cada medición hay un **calentamiento** (la
primera pasada se descarta) para no medir el arranque (imports perezosos, primer plan, cachés).

## Cómo se ejecuta

```bash
uv run python -m benchmarks.run          # the full measurement; `make benchmarks` does the same
```

**NO entra en `make audit`, y el motivo es de categoría, no de reloj**: un benchmark es una MEDICIÓN,
y su resultado es un número que cambia con la máquina. Lo que SÍ es verificable —que el banco SIGUE
CORRIENDO— vive en `make benchmarks-smoke`, que ejecuta el smoke test con
`SNAKEORM_REQUIRE_POSTGRES=true` para que un servidor ausente sea un FALLO y no un salto en verde.

Necesita un PostgreSQL accesible (el del devcontainer sirve tal cual). La conexión se resuelve desde
`.env` / el entorno con los mismos valores por defecto que el resto del proyecto (`DB_HOST`,
`DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`). Sin Postgres, imprime un mensaje claro y sale con un
código `!= 0`.

El banco es autocontenido: **crea su esquema, siembra lo que necesita, mide y LIMPIA** (borrando sus
tablas) al salir. No deja rastro en la base de datos.

## Tamaños configurables

Todos los tamaños viven en `benchmarks/harness.py`, en `DEFAULT_CONFIG` (fácil de subir o de bajar):
iteraciones de compilación y de emisión, tamaños de lote del INSERT, filas de las lecturas, número de
padres del include, y así. El smoke test (`test/benchmarks/test_smoke.py`) usa un `SMALL_CONFIG` para
correr rápido sin asertar tiempos.

## Una NOTA honesta

Estos números salen de **una máquina de desarrollo concreta**, contra **un solo motor**
(PostgreSQL), y **SIN comparación con otros ORMs** (SQLAlchemy, Django ORM, Peewee...). Sirven como
**línea base nuestra** para detectar regresiones y para sostener la tesis de que «compilar una vez
sale barato», NO como un ranking ni como una afirmación de que SnakeORM sea más rápido o más lento
que nadie. Una comparación entre ORMs sería otra decisión de diseño (un dominio equivalente, las
mismas garantías, variables controladas) que este banco no toma.
