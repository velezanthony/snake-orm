# Proceso de release

!!! warning "Este proceso NUNCA se ha ejecutado"

    `git tag` no devuelve nada: **cero tags, cero versiones publicadas**. Todo lo de abajo es el
    procedimiento previsto, no una rutina que alguien haya corrido. Antes del primer release hay una
    lista de bloqueantes en [Qué falta antes del primer release](#que-falta-antes-del-primer-release),
    y ninguno es opcional.

```bash
make audit                 # everything green first
uv build                   # produces dist/*.whl and dist/*.tar.gz
unzip -l dist/*.whl        # check: only snakeorm/ (+ py.typed)
uv publish                 # publish (or: twine upload dist/*)
git tag vX.Y.Z && git push --tags
```

El paquete se construye como un wheel de Python con [hatchling](https://hatch.pypa.io/). `make audit`
es la puerta local, y lo que exige está en [Testing](testing.es.md).

## El nombre de distribución NO es `snakeorm`

`pyproject.toml` declara `name = "snake-orm"`. `snakeorm` es solo el nombre de
**IMPORT** (`packages = ["src/snakeorm"]` bajo `[tool.hatch.build.targets.wheel]`).

O sea que hoy `uv publish` publicaría en PyPI un proyecto llamado `snake-orm`, que se
instala con `pip install snake-orm` y se importa como `import snakeorm`. Esa separación
es legal y habitual, pero es una decisión, no un accidente que descubrir en el momento de subir.
Quien haga el primer release tiene que o reclamar `snakeorm` en PyPI y renombrar el proyecto, o
aceptar el nombre actual y decirlo en el README.

## Versionado

SemVer (`MAJOR.MINOR.PATCH`), en `pyproject.toml` (`project.version`).

- **PATCH** — arreglos sin cambio de API.
- **MINOR** — funcionalidad nueva retrocompatible.
- **MAJOR** — cambios incompatibles de la API pública (`snakeorm/__init__.py`).

La versión actual es **`0.1.0`**, con lo que esas reglas todavía no aplican tal cual. En SemVer, todo
lo anterior a `1.0.0` es la fase de desarrollo inicial: la API pública no es estable y un cambio
rompedor sale en un salto MINOR (`0.1.0` → `0.2.0`), porque no hay MAJOR que gastar sin declarar la
API estable. Las reglas de arriba empiezan a ser literales a partir de `1.0.0`, y pasar a `1.0.0` es
un compromiso sobre `snakeorm/__init__.py` —la superficie que deriva `test/test_public_api.py`—, no
un hito de cantidad de funcionalidades.

## Qué viaja en el wheel

El layout `src/` garantiza que **solo el paquete se empaqueta**: `test/`, `benchmarks/` y
`examples/` NO entran. Verifícalo con `unzip -l dist/*.whl`.

El marcador `py.typed` (`src/snakeorm/py.typed`) es crítico: hace que mypy/pyright del CONSUMIDOR
reconozcan los tipos del ORM (PEP 561). Sin él, `import snakeorm` daría `Any` — justo lo que el
proyecto promete no hacer.

## Qué falta antes del primer release

Verificado contra el repo, no supuesto:

- **No hay job de publicación.** `.github/workflows/` tiene exactamente dos ficheros: `ci.yml`
  (gates) y `docs.yml` (publica en GitHub Pages). Ninguno corre `uv build` ni `uv publish`, no hay
  trigger `on: release` ni secreto de PyPI configurado. Todo el proceso es manual, desde un portátil.

## Pasos

1. `make audit` en verde (lint, formato, tipos, docs, tests).
2. Sube la versión en `pyproject.toml`.
3. Escribe la entrada del `CHANGELOG.md`, bajo un encabezado de versión en vez de `Unreleased`.
   Va solo en inglés, y el propio fichero explica por qué en sus primeras líneas.
4. `uv build`.
5. Verifica el wheel (`unzip -l`: solo `snakeorm/` + `py.typed`).
6. `uv publish` (o `twine upload dist/*`) — mira antes qué nombre de distribución estás subiendo.
7. `git tag vX.Y.Z && git push --tags`. Sería el primer tag del repositorio.

## El CI

`.github/workflows/ci.yml` corre en cada push a `main` y en cada pull request, en cuatro jobs — los
mismos que puedes correr en local desde [Montar el entorno](development.es.md):

- **`quality`** (así se llama en el YAML, sin traducir) — ruff, `ruff format --check`, `mypy .`,
  `mypy shared` desde `frameworks/`, `mypy --strict src/snakeorm/`, `pyright src/snakeorm/` y
  `pyright` sobre las tres apps de demostración. Ese último paso es el que más fácil se cae de una
  lista escrita a mano, y está aquí porque ya se cayó una vez. Va primero y sin matriz a propósito: si
  hay un error de lint o de tipos, no tiene sentido levantar un Postgres por cada pata de la matriz
  `tests` para descubrirlo.
- **`tests`** — la matriz completa, Python 3.11–3.14 × PostgreSQL/SQLite: el producto cartesiano
  entero y sin `exclude`, porque una versión probada solo contra SQLite es una versión de la que no
  sabes si habla con Postgres. MariaDB corre al lado para el e2e de MySQL. `if` no existe a nivel de
  `services:`, así que el contenedor de Postgres se levanta también en la pata de SQLite — unos
  segundos tirados frente a duplicar el job, que se descuadraría a la primera. La pata postgres pone
  `SNAKEORM_REQUIRE_POSTGRES=true`, que convierte en fallo un salto por falta de base de datos, y mide
  la cobertura.
- **`frameworks`** — las tres apps de demostración más la capa compartida, como matriz de cuatro
  patas (`shared`, `fastapi`, `flask`, `django`) con `fail-fast: false`. Éste también gatea, y es el
  único sitio donde el pipeline se ejercita entero.
- **`docs`** — `mkdocs build --strict`, donde cualquier aviso es un error.

`docs.yml` va aparte: publica en GitHub Pages en los push a `main` que tocan `docs/`, `mkdocs.yml` o
el propio workflow. Publica documentación, nunca un paquete.

Un release no debería salir con el CI en rojo.
