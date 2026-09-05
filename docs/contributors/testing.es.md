# Testing

```bash
uv run pytest                        # the whole suite
uv run pytest -m "not integration"   # deselects the MARKED ones, which is not "no database"
uv run pytest src/test/session/      # one directory
uv run pytest -q -k upsert           # by name
```

**`-m "not integration"` no promete «sin servidor».** Deselecciona los tests que LLEVAN el marcador,
y el marcador se pone a mano, fichero a fichero. Hay ficheros de `test/integration/` que hablan con
un motor de verdad y van sin él —`test_mysql_e2e.py`, `test_async_mysql_e2e.py`,
`test_round_trip_property.py`, `test_session_database_isolation.py` y unos pocos de
`test/migration/`, entre otros—, así que con los contenedores levantados ese filtro los ejecuta
contra el servidor real. Si lo que quieres es no tocar nada, nombra los directorios que SÍ quieres en
vez de confiar en un filtro para excluir los que no.

**Strict TDD**: el test primero, la implementación después. Cada test lleva un docstring `""" """`
explicando QUÉ verifica.

Los tests viven en `src/test/` y **reflejan `src/snakeorm/`**: el de
`snakeorm/metadata/column.py` está en `test/metadata/`. Es un índice, no arquitectura duplicada.

Cuántos hay no está escrito aquí, porque un número en prosa se queda obsoleto a la semana de
teclearlo y a partir de ahí se lee como un hecho. Ésta es la orden:

```bash
uv run pytest --collect-only -q | tail -1        # how many the suite collects today
```

## Tipos de test

- **Unitarios** — la mayoría. Sin base de datos.
- **Integración** — hablan con un servidor real, y **ningún directorio es señal fiable tampoco**: la
  mayoría vive en `test/integration/`, `test/scenarios/` y parte de `test/migration/`, pero también
  hay ficheros en `test/cli/`, `test/dto/`, `test/session/`, `test/examples/` y `test/benchmarks/`.
  Lo que SÍ contesta es qué importa un fichero —`NO_SERVER_REASON` o `NO_MYSQL_REASON` de
  `test/conftest.py`— y la forma honesta de correr el conjunto es levantar los contenedores y poner
  las puertas `SNAKEORM_REQUIRE_*`, para que un motor ausente sea un fallo y no un salto.
  `@pytest.mark.integration`
  cubre a la mayoría y NO a todos —se pone a mano—, así que tomarlo por la definición del conjunto es
  justo el error que avisa la primera sección. Tampoco todos necesitan servidor:
  `test/integration/test_sqlite_e2e.py`, `test_sqlite_migrations.py` y
  `test_sqlite_introspection.py` corren en cualquier máquina, porque SQLite viene en la biblioteca
  estándar (y ninguno de los tres lleva el marcador). Los de PostgreSQL se **saltan con gracia** sin
  servidor, y los tres ficheros de MariaDB (`test_mysql_e2e.py`, `test_async_mysql_e2e.py`,
  `test_mysql_introspection.py`) se saltan sin `MYSQL_HOST`. Ver
  [Cuándo un salto es un fallo](#cuando-un-salto-es-un-fallo).
- **Contrato de tipos** (`@pytest.mark.typecheck`) — `test/typing/` lanza mypy Y pyright sobre
  `cases_positive.py` (debe tipar) y `cases_negative.py` (debe fallar EXACTO en las líneas con
  `# EXPECT: <codigo>`). Lento; se excluye con `-m "not typecheck"`.
- **Basados en propiedades** — [Hypothesis](https://hypothesis.readthedocs.io/) declara la
  invariante y busca la entrada que la rompe, en vez de enumerar los casos que a alguien se le
  ocurrieron. `test/test_pyliteral_property.py`: para CUALQUIER string, `str_lit` produce un literal
  parseable que evalúa de vuelta al string exacto (es un primitivo de seguridad: una fuga ahí es una
  RCE en el scaffolder). `test/integration/test_round_trip_property.py`: para CUALQUIER valor de
  CUALQUIER tipo soportado, lo escrito vuelve idéntico, en los dos motores. Cuando algo se rompe,
  Hypothesis lo minimiza al ejemplo más pequeño que falla.

## Las redes mecánicas

No son tests de una funcionalidad. Cada una ata una convención que se erosionaba en silencio, y cada
una existe porque ya se erosionó una vez.

- **Aciclicidad** — `test/test_layering.py`: falla si dos paquetes se importan en círculo. Se mide
  por PAQUETE, no por módulo. Antes de existir había un ciclo real (`decorators <-> query`) y
  veintiocho imports escondidos dentro de funciones.
- **La documentación compila** — `test/test_docs.py`: cada bloque ```` ```python ```` de `docs/`
  parsea, cada `from snakeorm import X` existe de verdad, y cada modelo que la documentación declara
  COMPILA. La tercera comprobación es la que caza la mentira cara: `snake_column()` sobre un
  `datetime` importa un nombre que existe, parsea perfectamente, y es un error del compiler. El
  pseudocódigo va en ```` ```text ````, las transcripciones de REPL en ```` ```pycon ````.
- **La documentación es bilingüe** — `test/test_docs_are_bilingual.py`: cada página publicada existe
  en los DOS idiomas (`pagina.md` inglés, `pagina.es.md` castellano). `mkdocs-static-i18n` cae al
  idioma por defecto, así que una página sin traducir nunca rompe la build — que es justo lo que
  hace invisible la deriva. Comprueba que la página EXISTA; que las dos digan lo mismo no es algo
  que un test pueda medir.
- **La tabla de tipos** — `test/test_type_table_doc.py`: lee la tabla de tres columnas de
  `docs/users/guide/columns.md` (Postgres, MySQL, SQLite) y le pregunta al dialecto que la produce.
  Ya había derivado: decía que MySQL "rechaza" `SnakeUtc`, `timedelta` y `list[int]` cuando los tres
  caen a TEXT. Una fila nueva sin entrada aquí también falla: una tabla a medias miente igual que
  una equivocada.
- **El idioma del código es una convención, no una red.** Aquí hubo tres detectores y se han
  borrado: detectaban castellano **listando castellano**, y una lista negra falla EN ABIERTO — solo
  encuentra lo que ya sabe buscar. Un test llamado «las cadenas están en inglés» que comprueba
  «ninguna cadena casó con mi lista» es peor que no tener test, porque fabrica confianza. La
  convención sigue igual, el código habla inglés; lo que ya no está es el detector que fingía
  garantizarlo. Una EXISTENCIA y una IGUALDAD se comprueban mecánicamente, un idioma no.
- **La propia red anti-salto** — `test/test_ci_guard.py`: `conftest.py` reconoce un salto por falta
  de servidor por su MOTIVO, que es una convención, y las convenciones se erosionan. Esto ata esa
  frase al árbol de tests real, así que el día que alguien la redacte distinto el test falla en vez
  de quedarse fuera de la red sin decirlo.
- **La API pública** — `test/test_public_api.py`: `snakeorm/__init__.py` es un facade que re-exporta
  con alias redundante y sin `__all__`, así que la superficie pública se DERIVA en runtime en vez de
  mantenerse como una lista de strings en paralelo. El contrato: la superficie mínima para declarar,
  consultar y ejecutar está publicada, y NADA FORÁNEO (stdlib o terceros) se cuela.

## Las matrices de dialecto

Es lo primero que rompe quien toca un dialecto, y este proyecto arrastra un patrón de bug que se
repite: **algo implementado o verificado en N-1 de N hermanos**. Las claves foráneas existían en
Postgres y no en SQLite. `AsyncSession` salió con doce de veintidós métodos.

- `src/test/migration/test_emitter_dialect_matrix.py` — todos los emisores de DDL contra los tres
  motores. Cuántos hay no está escrito aquí ni está escrito allí:
  `test_the_invocation_table_covers_every_emitter` los LEE de `migration/ddl.py`, así que un emisor
  nuevo entra en la matriz por el hecho de existir. No exige que todo funcione en todas partes; exige que cada emisor haga UNA de dos
  cosas: emitir SQL que el motor ACEPTA, o estar cubierto por `realize()`, que lo para en el PLAN
  con un motivo legible. La tercera opción, la prohibida, es emitir SQL que el motor rechaza, para
  que reviente con un error de sintaxis críptico en mitad de un despliegue.
- `src/test/integration/test_query_dialect_matrix.py` — cada camino de CONSULTA que emite una
  subconsulta correlacionada. Ejecuta comportamiento con datos reales en vez de enumerar nombres, y
  cubre un punto ciego que dejaron las demás redes: siete APIs públicas (`.any()`, `.count()`,
  `.sum_()`, `.avg()`, `.min_()`, `.max_()`, `session.annotate()`) estaban rotas en SQLite porque
  dos emisores construían la referencia a la tabla hija a mano en vez de pasar por `qualified()`.
  Se prueba en SQLite porque es donde la ausencia de esquemas lo destapa.

## Cuándo un salto es un fallo

Un test que se salta en silencio es peor que un test que no existe.

Los tests que hablan con Postgres se saltan con gracia cuando no hay servidor, y eso está BIEN en el
portátil de alguien que solo quiere tocar el compilador. En CI es exactamente lo contrario: allí el
servidor tiene que estar, y un `skip` significa que la infraestructura falló y la suite lo tapó.

Nadie mira el número de `skipped`; todo el mundo mira si pone `passed`, así que un `DB_PORT` mal
propagado puede dejar cien tests de integración saltando con la suite reportando verde.

```bash
SNAKEORM_REQUIRE_POSTGRES=true uv run pytest
```

Con esa variable activa, un salto por falta de base de datos se reporta como FALLO, nombrando el
test y el motivo original. `.github/workflows/ci.yml` la pone en la pata postgres de la matriz.

**El valor se lee como lista BLANCA, y hay UNA grafía por lado.** Sin poner es apagado, `true` y
`false` deciden, y cualquier otra cosa para la corrida antes de recolectar diciendo qué ha leído:

```text
ERROR: SNAKEORM_REQUIRE_POSTGRES='0' is not a boolean: write 'true' or 'false', or leave it unset. It is not guessed either way, and that is deliberate — reading it as on would hide a switch you meant to turn off, and reading it as off would hide the very skips this net exists to make loud.
```

Así que `false` es apagado, y `0`, `no`, `off` y `1` no son «apagado»: abortan. Ése es el arreglo de
lo que esto era antes —una lista NEGRA donde `0`, `false` y `no` significaban apagado y CUALQUIER
otra cosa significaba encendido—, con lo cual `SNAKEORM_REQUIRE_POSTGRES=off` se leía como
claramente apagado y encendía la red, en silencio. Una lista más larga tiene la misma forma y solo
mueve el borde; negarse a adivinar lo elimina, y las dos adivinanzas posibles se equivocan igual: una
esconde un interruptor que querías apagar, la otra esconde justo los saltos que esta red existe para
hacer ruidosos.

**La red se activa por el MOTIVO del salto, no por la carpeta.** La primera versión miraba una lista
de directorios (`integration`, `scenarios`) y se le escapaban dos ficheros de `test/migration` que
también necesitan servidor — precisamente los de atomicidad y migraciones de datos, que son de los
que más duele no ejecutar. Una lista de sitios hay que mantenerla y se queda obsoleta; el motivo
viaja con el test, así que un fichero nuevo en una carpeta nueva queda cubierto sin que su autor
tenga que saber que esto existe.

El CI añade una segunda comprobación encima, porque el hook no puede cazar lo que no llega a
recolectarse (un `conftest` roto, un `--ignore` que se cuela, un renombrado de directorio): cuenta
la recolección de `src/test/integration` y `src/test/scenarios` y falla por debajo de 100. El umbral
es un suelo y no un objetivo, así que es la única cifra que hay aquí: lo que recolectan hoy lo dice
`uv run pytest --collect-only -q src/test/integration src/test/scenarios | tail -1`.

## Variables de entorno

| Variable | Default | Qué hace |
| --- | --- | --- |
| `SNAKEORM_REQUIRE_POSTGRES` | apagada | un salto por falta de PostgreSQL pasa a ser un fallo |
| `SNAKEORM_REQUIRE_MYSQL` | apagada | lo mismo, para el servidor MySQL/MariaDB |
| `DB_HOST` | `127.0.0.1` | host de PostgreSQL |
| `DB_PORT` | `5432` | puerto de PostgreSQL |
| `DB_USER` | `postgres` | usuario de PostgreSQL |
| `DB_PASSWORD` | `snakeorm_pass` | contraseña de PostgreSQL |
| `DB_NAME` | `snakeorm_db` | base de datos de PostgreSQL |
| `SNAKEORM_DSN_<NAME>` | — | DSN completo de una conexión CON NOMBRE (tests multi-BD) |
| `MYSQL_HOST` | — | **sin default**: sin ella `test_mysql_e2e.py` se salta entero |
| `MYSQL_PORT` | `3306` | puerto de MariaDB/MySQL |
| `MYSQL_USER` | `root` | usuario de MariaDB/MySQL |
| `MYSQL_PASSWORD` | vacío | contraseña de MariaDB/MySQL |
| `MYSQL_DB` | `snakeorm_db` | base de datos de MariaDB/MySQL |

El juego `DB_*` se resuelve en `snakeorm/core/config.py`, el único sitio que traduce entorno
(incluido el `.env`) a un DSN. Cómo levantar cada servidor está en
[Entorno de desarrollo](development.es.md#bases-de-datos).

## Cobertura

```bash
make coverage        # report in the terminal, with the missing lines
make coverage-html   # browsable report in htmlcov/
```

Configurada en `pyproject.toml` con `branch = true` y `source = ["snakeorm"]`. Se excluyen
`@overload`, `if TYPE_CHECKING:` y los cuerpos que son literalmente `...`: un overload es una firma
sin cuerpo que nadie ejecuta jamás (`session.py` tiene cuatro seguidos solo para `select`), y
contarlos como no cubiertos mide el estilo del código, no lo que la suite ejercita.

**NO hay `fail_under` a propósito, y no es un descuido que haya que arreglar.** La decisión es MEDIR
E INFORMAR. Un umbral puesto a ojo acaba siempre en uno de dos sitios: bloqueando un cambio bueno, o
bajándose hasta no querer decir nada. El CI ya la mide — en la pata de postgres, no en la de SQLite,
porque sin servidor los tests de integración se saltan y el número saldría bajo por una razón que no
tiene nada que ver con la calidad de la suite.

## Las apps de demostración

```bash
make frameworks-test          # the three apps + the shared layer
make frameworks-test-shared   # only the shared domain
make frameworks-test-flask    # only Flask
make frameworks-test-django   # only Django
make frameworks-test-fastapi  # only FastAPI
```

Las tres apps de `frameworks/` son el ÚNICO sitio donde el pipeline se ejercita entero y de verdad:
modelo → compilador → grafo de metadata → migración → DDL → sesión → HTTP, contra una base real
(SQLite) y con las migraciones aplicándose. La suite de `src/test` prueba cada tramo; esto prueba
que los tramos encajan.

Gatean en el CI como job propio, con una matriz de cuatro patas (`shared`, `fastapi`, `flask`,
`django`) y `fail-fast: false`, así que el check rojo YA dice cuál se rompió. `shared` va primero: es
el dominio que las tres comparten, así que un fallo ahí son tres fallos derivados de una sola causa.

## Los gates (lo que exige el CI)

```bash
uv run ruff check .                  # lint, over the WHOLE repo
uv run ruff format --check .         # formatting, over the WHOLE repo
uv run mypy .                        # type-check of the repo (lenient)
cd frameworks && uv run mypy shared  # the demos' shared layer (NOT optional)
uv run mypy --strict src/snakeorm    # the "ZERO Any" gate over the package
uv run pyright src/snakeorm          # pyright (what Pylance sees by default)
uv run pyright frameworks/django frameworks/flask frameworks/fastapi   # pyright over the demos
uv run mkdocs build --strict         # the documentation builds with no warnings
uv run pytest                        # the suite
make frameworks-test                 # the three demo apps + the shared layer
```

**Las dos líneas de ruff dicen `.` y no `src`, y eso es lo importante.** Miran el repo ENTERO,
`frameworks/` incluido, porque la alternativa ya falló: con los targets fijados a `src/`, un fichero
de demo mal formateado salía verde en local y rojo en el pipeline — y no era hipotético, había tres
ficheros de demo sin formatear en `main` mientras `make audit` decía que todo estaba bien. Un gate que
se anuncia como «lo que exige el CI» y mira menos es el gate incompleto que se hace pasar por
completo.

`make audit` corre ésos y MÁS: es un SUPERCONJUNTO de los gates del CI, y la lista de prerrequisitos
vive en la línea `audit:` del `Makefile` en vez de copiarse aquí, porque una lista copiada a mano es
una lista que se queda obsoleta. Lo que añade sobre este bloque es `typecheck-react` y `lint-react`
para el cliente React, más `examples` y `benchmarks-smoke`. Esos dos últimos van a propósito JUSTO
ANTES de `test`, y la posición es la decisión: los dos exigen Postgres y tardan segundos, mientras que
`test` tarda minutos y sin Postgres se salta en verde. Delante, un `make audit` a ciegas se para en el
segundo tres diciendo que no hay base de datos en vez de gastar dos minutos fabricando confianza.
**Todo tiene que estar en verde.** `pyright-frameworks` es el que se cae fácil de una lista escrita a
mano: es la mitad de las demos de lo que `make pyright` hace por el paquete, y existe porque `pyright`
estaba fijado a `src/snakeorm` mientras las tres apps se quedaban sin mirar.

El segundo type-check no es opcional. `frameworks/shared/` se importa a sí mismo como `shared`, y
eso no resuelve desde la raíz del repo: lanzado desde ahí, mypy convierte la capa entera en `Any` y
dice Success. Se comprueba DESDE `frameworks/`, que es donde `shared` resuelve.

Dos de ellos merecen que se diga su porqué. `mypy --strict` corre sobre el PAQUETE y no sobre el
repo: es la tesis del proyecto gateada ("cero `Any`"), y ponerlo global obligaría a tipar en
estricto también los tests. `pyright` se comprueba en modo basic, el de por defecto de Pylance,
porque el modo strict de pyright marca el `Any` interno de los descriptores recursivos —que es la
técnica misma del proyecto—, así que gatearlo sería pelearse con el propio diseño.

## Reglas al escribir tests

- Test PRIMERO (rojo), luego implementación (verde).
- Docstring obligatorio con qué verifica.
- Para SQL, comprueba el `(sql, params)` emitido; no interpoles valores.
- End-to-end en `test/integration/` y `test/scenarios/`.
- Si un test necesita servidor, sáltalo con la frase del repo —la que publica `test/conftest.py`—
  para que la red anti-salto lo cubra. Inventarse una redacción lo deja fuera, y `test_ci_guard.py`
  lo dirá.
- Al tocar un dialecto: las dos matrices de arriba, antes que nada.
- Cada estructura nueva de migración: test de ciclo completo
  (modelo → `autodetect` → fichero → `replay` → estado idéntico).
