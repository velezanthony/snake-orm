# Contribuir a SnakeORM

> La guía de contribución en inglés y castellano: [https://velezanthony.github.io/snake-orm/contributors/](https://velezanthony.github.io/snake-orm/contributors/).
> Ésta es la versión castellana de `CONTRIBUTING.md`; la de por defecto, en inglés, vive a su lado.

Gracias por el interés. SnakeORM es un ORM **dataclass-first** y **type-first** para Python 3.11+: el
sistema de tipos es la única fuente de verdad y el runtime solo ejecuta SQL sobre metadata ya
compilada. Antes de tocar código, esta guía te deja el entorno listo y te explica las reglas del
juego.

## Entorno de desarrollo

El proyecto usa [uv](https://docs.astral.sh/uv/) para gestionar el entorno y las dependencias.

```bash
# Install EVERYTHING (package + optional extras + dev tooling)
uv sync --all-extras --all-groups
```

Hay un **devcontainer** (`.devcontainer/`) que levanta Python y **los dos** motores listos para usar;
si trabajas con VS Code, "Reopen in Container" y no hay nada más que instalar.

Los tests de integración necesitan **dos** motores, no uno. Con Docker:

```bash
docker compose up -d db mysql   # Postgres and MariaDB (see docker-compose.yml)
```

Cada motor lee sus propias variables del entorno (o de un `.env`): Postgres coge `DB_HOST`,
`DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`, y MySQL/MariaDB coge `MYSQL_HOST`, `MYSQL_PORT`,
`MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DB`. Copia `.env.example` a `.env` y ajústalo.

En el compose hay además un visor de trazas **Jaeger**, detrás de un perfil para que nunca arranque
con los motores. El canal de debug `otel` exporta hacia él:
spans OTLP a `http://localhost:4318/v1/traces` —el puerto que publica este servicio—, cambiable con
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`. Es el único canal pensado para producción, porque los spans
van a tu colector y no a la página de nadie.

```bash
docker compose --profile tracing up -d jaeger   # UI at http://127.0.0.1:16686, OTLP on 4317/4318
```

## Estructura del repo

Disposición `src/`: **solo el paquete se empaqueta**; los tests y todo lo demás viven bajo `src/`
como hermanos, pero NO entran en la wheel.

```
src/
├── snakeorm/     the package (flat domains: metadata, compiler, sql, dialects, drivers, ...)
├── test/         the suite (mirrors the structure of snakeorm/)
├── benchmarks/   performance measurement
└── examples/     executable examples
docs/             documentation (mkdocs)
```

El diseño detallado está en [`docs/contributors/architecture.md`](docs/contributors/architecture.es.md).

## Ejecutar los tests y las puertas

```bash
make test           # the suite (uv run pytest)
make audit          # the full gate CI runs (lint + format + types + tests)
```

O a mano:

```bash
uv run pytest                        # every test (see the warning below before trusting it)
uv run pytest -m "not integration"   # unit tests only, no DB
uv run ruff check .                   # lint
uv run ruff format --check .          # formatting
uv run mypy .                         # type-check of the package
make typecheck-frameworks             # type-check of frameworks/shared (it is TWO commands)
uv run mypy --strict src/snakeorm     # the "ZERO Any" gate over the package
uv run pyright src/snakeorm           # pyright (what Pylance sees)
uv run mkdocs build --strict          # the documentation builds without warnings
```

**Todo tiene que estar verde** antes de abrir un PR.

CI corre las mismas puertas y **una más que la lista de arriba se deja**: `make pyright-frameworks`,
sobre las tres demos. `make audit` compone el conjunto entero en local, así que correr eso es la
forma de saber qué va a decir CI — la lista de arriba es lo que tecleas mientras trabajas, no el
contrato.

### Correr sin base de datos NO es verificar

Sin los motores levantados, los tests que hablan con un servidor de verdad se convierten en SALTADOS
y **la suite sale verde igual**. Dos puertas, una por motor, convierten «saltado por falta de
servidor» en un fallo:

```bash
SNAKEORM_REQUIRE_POSTGRES=true SNAKEORM_REQUIRE_MYSQL=true uv run pytest -q -rs
```

Con las dos puestas, ningún salto puede deberse a un motor ausente: los que queden declaran una
capacidad (`MySQL cannot: STORED_FUNCTIONS`…). `-rs` imprime cada motivo, y **el motivo es el
criterio, no la cifra** — un salto que no diga «cannot» es un test que nadie ha ejecutado y nadie ha
echado de menos.

## Reglas del proyecto

- **Strict TDD**: el test va PRIMERO, la implementación después.
- **Cada test lleva un docstring** `""" """` explicando QUÉ verifica.
- **CERO `Any`**: la puerta es `mypy --strict src/snakeorm`. El tipo siempre proviene de Python; la
  metadata solo añade información de SQL.
- **El CÓDIGO habla un idioma: inglés.** Identificadores, comentarios, docstrings, mensajes al
  usuario y cualquier cadena que lleve el código. Este apartado llegó a pedir comentarios en
  castellano mientras el proyecto era para aprender; desde que la referencia de API se publica, el
  repositorio tiene un idioma y solo uno. Mantenlos concisos: explica el «porqué» no obvio, nada de
  ensayos.
- **La DOCUMENTACIÓN habla dos**, y ésa es una decisión distinta que no hay que confundir con la de
  arriba: dos lenguas de prosa sobre UN SOLO código y unos mismos ejemplos. Cada página publicada
  lleva su `.es.md`, y las dos comparten un bloque de código idéntico —
  `test_docs_are_bilingual.py` y `test_docs_share_one_code.py` lo comprueban. Un comentario dentro
  de un ejemplo es código, no prosa: viaja idéntico en las dos.
- **El SQL va siempre parametrizado**: la emisión devuelve `(sql, params)`; los valores NUNCA se
  interpolan en el string. Nada de `repr()`/f-strings con valores.
- **Aciclicidad**: los paquetes no importan en círculo (`test/test_layering.py` lo verifica).
- **Conventional commits**: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`...

## Añadir un motor (dialecto + driver)

La costura se parte en dos ejes que nunca se mezclan:

- **Dialect** — cómo se ESCRIBE el SQL (placeholders, quoting, mapeo de tipos). Es un `Protocol`.
- **Driver** — cómo se EJECUTA (la librería DBAPI, conexión, cursor, transacción). Hay **dos**, uno
  síncrono y otro asíncrono: generar SQL no tiene color, así que el dialecto se reutiliza tal cual y
  lo único que se escribe dos veces es la ejecución. Los tres motores actuales tienen la pareja; si
  el tuyo no tiene librería async nativa, `threaded.py` sirve el síncrono desde un hilo propio, que
  es lo que hace `aiosqlite` por dentro.

Añadir un motor tiene que ser **un fichero nuevo, no un refactor**: una implementación del
`Protocol` del dialecto en `dialects/` y las del driver en `drivers/`. Los modelos y la metadata son
100% agnósticos del motor. Ver [dialectos](docs/users/engines/dialects.es.md).

**Y hay una tercera cosa que no es opcional: el catálogo `Cap`.** Tu dialecto contesta al catálogo de
capacidades ENTERO con `Full()`, `Degraded(reason)` o `Nope(reason)`. No es documentación: si te
dejas una, el ORM revienta al importar el dialecto, y a propósito — en un conjunto, la capacidad que
olvidaste declarar sencillamente no está, y «no está» se lee como «no soportado». Un valor por
defecto en silencio, en el ORM que grita.

De ahí salen las dos cosas que hacen creíble el multi-motor: el plan se para ante lo que el motor no
puede hacer, y la sesión avisa UNA vez por salvedad. El motivo que escribes en un `Degraded` es el
texto que un usuario va a leer, así que dile QUÉ se degrada —ordenar, comparar, operar— y no que «no
está soportado»: un tipo sin equivalente cae a `TEXT` y funciona, el valor entra y sale exacto. Lo
que no se hace nunca es guardarlo peor y callarse.

## Trabajar en las demos (`frameworks/`)

Tres aplicaciones sobre UNA capa de dominio: Django y Flask renderizan HTML, FastAPI contesta JSON
sobre una `AsyncSession`. El framework no lleva lógica — parsea, llama a `shared/` y renderiza.

Las convenciones (cómo se declara un endpoint en cada uno, por qué el SSR usa solo GET y POST, por
qué no se usan ni `contrib.auth` ni `flask-login`, y qué redes se te van a poner rojas) están en
[Trabajar en las demos](docs/contributors/frameworks.es.md). Léelo ANTES de añadir una ruta: la
mitad de esas redes existen porque a una demo le creció una página que las otras dos nunca tuvieron.

## Abrir un Pull Request

1. Crea una rama desde `main`.
2. Test primero, implementación después; deja `make audit` en verde.
3. Conventional commits, mensajes claros.
4. Abre el PR describiendo el QUÉ y el PORQUÉ.
