# Apps de demostración — Django · Flask · FastAPI

Tres apps que usan **SnakeORM** montando el MISMO dominio sobre cada framework, con la **herramienta
de debug del ORM** integrada. Sirven de ejemplo y de test de integración real: prueban los
adaptadores `snakeorm.contrib` contra Django, Flask y FastAPI de verdad.

El dominio son diez paquetes y 29 tablas. SEIS tienen páginas SSR y cada uno enseña algo distinto a
propósito: **blog** (login/registro + CRUD de posts) es la forma de todos los días —relaciones sin
N+1, N—N de etiquetas—; **inventory** es la difícil — el stock se identifica por el PAR
`(almacén, sku)`, así que la clave viaja en la URL en dos mitades y los movimientos cuelgan de una
clave ajena de dos columnas—; **orders** es la única sección donde dos clientes quieren la misma
unidad; **billing** es el dinero, de solo lectura a propósito; **taxonomy** es el N—N con puente
explícito; y **logistics** es la que MIDE — la distancia a un depósito es una raíz cuadrada sobre una
suma de cuadrados, y la carga de una hora es una ventana cuya anchura es un VALOR y no un número de
filas. Los otros cuatro son solo JSON. Hacia dónde va esto, más abajo.

## Estructura

```
frameworks/
├── shared/          código compartido (fuente ÚNICA de verdad)
│   ├── data/          datos de siembra (definidos una vez, reusados por los 3 seeders)
│   ├── models/        modelos SnakeORM, un fichero por dominio
│   ├── selectors/     lecturas del dominio
│   ├── services/      escrituras y reglas del dominio
│   ├── usecases/      la operación completa de cada acción (escrita una vez)
│   ├── viewmodels/    la forma PLANA que lee una plantilla (dicts tipados, sin modelos)
│   ├── web/           nav.py: el catálogo del lateral, sin una sola URL dentro
│   ├── dto/           la forma que sale por JSON
│   ├── tests/         los tests del dominio (SQLite en memoria, sin servidor)
│   ├── auth.py        hash/verify de contraseñas (scrypt, solo stdlib)
│   └── config.py      lee el .env (raíz) y elige SQLite, PostgreSQL o MySQL
├── django/          demo Django  (SSR + API)
├── flask/           demo Flask   (SSR + API)
└── fastapi/         demo FastAPI (solo API)
```

**`viewmodels/` es la capa que hay que entender**, porque no estaba y su ausencia costaba dinero. Una
plantilla que recorre `post.author.username` está **cargando una relación en la capa de
presentación**, donde ningún `assert_queries` mira: hoy funciona porque el selector hizo el
`include`, y el día que alguien lo quite la página sigue pintando — con una consulta por fila. El
viewmodel navega las relaciones y entrega primitivas ya formateadas, así que la plantilla no puede
disparar una consulta ni queriendo. Y de paso hace baratos los dos juegos de plantillas: si las dos
leen la misma forma plana, tener dos ficheros cuesta el HTML y nada más.

## Hacia dónde van las demos

**Esto va a crecer, y a propósito.** Las demos no son un escaparate bonito: son el único sitio donde
el ORM se ejercita como lo ejercitaría una aplicación de verdad, con un servidor delante, una base
real y un usuario haciendo clic. Un test unitario prueba que una pieza funciona; una demo prueba que
funciona **cuando algo la usa**.

Y ahí está el problema que justifica el trabajo: `frameworks/` toca **13 de los 24 métodos de
`SnakeSession`** y **7** de la API de usuario de `SnakeQuery`. Esa cuenta no está escrita aquí a
mano —envejecería— sino que la sostiene un test, `shared/tests/test_orm_api_coverage.py`, que
enumera las dos APIs por introspección y lleva la lista de lo NO ejercitado con su motivo. Falla en
las dos direcciones: al cubrir un método, hasta que se tacha de la lista; y al perder uno que ya
estaba cubierto. **No cuentan los tests**, y es deliberado: un `session.savepoint()` metido para que
el método tenga un llamante prueba que el método existe, que no estaba en duda.

Lo que no toca nadie no es marginal:

- **la sesión ASÍNCRONA entera.** FastAPI *es* async y usa la síncrona, así que `AsyncSession`,
  `AsyncDriver`, el pool async y la paridad sync/async solo los prueba `src/test`, nunca una app.
- **`for_update`** — la reserva de stock del inventario es el caso de manual, y sin bloqueo de fila
  es una carrera. Además SQLite declara `ROW_LOCKING: Nope`, así que ejercitaría el aviso de
  degradación en una app real.
- **`iterate()`** — el streaming es donde viven los fallos de memoria.
- **`savepoint()`**, **`set_isolation()`**, **`raw()`/`call()`**, **`recursive`**, los compuestos
  (`union`/`intersect`/`except_`), **`snake_trigger`**, **`snake_discriminator`** (polimorfismo),
  **multi-base** y casi todas las operaciones de migración (`RunPython`, `RunSQL`, `AlterColumn`…).

Nada de eso se prueba con un blog de quince posts. **Hace falta una aplicación medianamente grande**
—varios dominios navegables, listados que paginen de verdad, operaciones que ocurran dentro de una
transacción con pasos que puedan fallar— porque esas funcionalidades solo aparecen cuando algo
**tiene motivo** para pedirlas. Un `savepoint` metido para que salga en la demo no prueba nada; un
`savepoint` en una operación de varios pasos que revierte la mitad, sí.

Por eso el armazón (`layout/base.html`) trajo desde el principio más de lo que las páginas de
entonces necesitaban: landmarks nombrados, salto al contenido, región de avisos y pie. **Meter eso
después, en veinte páginas, es de esos trabajos que no hace nadie.** El lateral entró por la misma
razón, cuando todavía había tres secciones.

El plan completo, con sus cinco fases y sus puertas, está en `docs/planning/frameworks/roadmap.md`.

Lo que NO va a cambiar: los dos juegos de plantillas siguen siendo dos, la lógica sigue viviendo en
`shared/`, y cada framework sigue siendo un envoltorio.

### Las plantillas no llevan comentarios

Ni uno. Si una plantilla necesita un párrafo que la explique, es que se le ha colado lógica — y la
lógica vive en Python, en `shared/viewmodels/` y `shared/usecases/`, que es donde este repositorio
escribe sus razones. Los tres bloques `{# #}` que quedaban se fueron a los docstrings de
`apps/blog/urls.py` y `apps/lab/urls.py` (y sus equivalentes en Django), que es su sitio.

## Estilos: Tailwind con componentes

Un solo CSS para las demos, en `shared/static/app.css`. **Node hace falta para RECONSTRUIRLO, nunca
para correr una demo**: el fichero construido está commiteado, así que las tres arrancan solo con
`uv` y funcionan sin red.

```bash
cd frameworks
npm install          # una vez
npm run build:css    # tras tocar shared/static/src/app.css
npm run watch:css    # mientras se maqueta
```

La fuente es `shared/static/src/app.css` y todo lo que hay dentro es un **componente**, no una
utilidad suelta. Una plantilla escribe `class="btn btn-primary"`, no catorce utilidades en fila: el
día que cambian los botones, cambian ahí y no en veintisiete ficheros. Las utilidades quedan para lo
que sale una vez; lo que aparece dos veces se gana un nombre.

Vocabulario disponible: `btn` (+ `btn-primary` / `btn-ghost` / `btn-danger`, `btn-sm` / `btn-md`),
`card` (+ `card-head` / `card-body` / `card-foot` / `card-title` / `card-sub`), `form` (+ `field` /
`label` / `input` / `textarea` / `select-inline` / `check`), `table-wrap` + `table` + `num`,
`dl` (pares campo/valor de UN registro), `pager` + `pager-info`,
`alert` (+ `alert-ok` / `alert-error`), `badge` (+ `badge-ok` / `badge-muted`), `topbar` / `nav-link`
/ `layout` / `sidebar` (+ `sidebar-group` / `sidebar-title` / `sidebar-link` / `sidebar-blurb`) /
`page` / `stack`, `h1` / `lede` / `muted` / `code` / `empty`.

Dos estados se pintan desde el HTML y no desde una clase, porque así el lector de pantalla se entera
igual que el ojo: `.nav-link[aria-current="page"]` y `.sidebar-link[aria-current="page"]` marcan la
página actual, y `.btn[aria-disabled="true"]` atenúa el borde de una paginación. Una plantilla NO
escribe `opacity-50`: escribe el atributo y el estilo lo sigue.

Las plantillas son DOS juegos, uno por framework, y es a propósito: una plantilla que no nombra ni a
Django ni a Flask deja de ser la que un dev de cualquiera de los dos reconoce como suya, y estas
demos existen para leerse y copiarse.

## Configuración: `.env` en la RAÍZ del repo

Un **único `.env` en la raíz del repositorio** configura el ORM Y las tres demos — para no repetir la
conexión. Cópialo desde la plantilla (`cp .env.example .env`; la herramienta no genera ficheros
`.env` por política de permisos). **Sin `.env`, las demos corren contra SQLite por defecto.**

Las demos **reutilizan la misma conexión `DB_*` que el ORM**; solo añaden un interruptor de motor y
una base de datos por framework:

```dotenv
# Conexión a Postgres (único servicio en Docker; ORM y demos corren en el host y conectan por el
# puerto publicado). La comparten el ORM y las demos. `DB_PORT` es la MISMA variable con la que
# docker-compose publica el contenedor, así que cambiarla aquí mueve las dos puntas a la vez; no se
# fija un número en la documentación porque entonces habría dos fuentes de verdad y una envejecería.
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=snakeorm_pass
DB_NAME=snakeorm_db

# Motor de las tres demos a la vez: sqlite (cero setup) | postgres (reusa DB_* de arriba).
DB_BACKEND=sqlite

# Una BD por framework cuando DB_BACKEND=postgres (se crean solas; host/user/... salen de DB_*).
DJANGO_DB_NAME=django_demo
FLASK_DB_NAME=flask_demo
FASTAPI_DB_NAME=fastapi_demo

# Clave para firmar las cookies de sesión del login. CÁMBIALA.
DEMO_SECRET_KEY=change-me
```

**Cambiar de SQLite a PostgreSQL (o al revés) es editar UNA línea** (`DB_BACKEND`): las tres demos lo
respetan. Con `postgres`, cada framework acaba en su propia base (`django_demo`, `flask_demo`,
`fastapi_demo`) dentro del mismo servidor docker, reusando la conexión `DB_*` del ORM.

### Al correr los tests, esos nombres son una BASE y no un nombre

Una base por framework separa a Django de Flask; lo que no separa es **una corrida de otra corrida
del mismo framework**, y varias sesiones de trabajo comparten un solo servidor. Dos suites a la vez
significa que una está reconstruyendo el esquema que la otra está leyendo — y como la siembra es
determinista, la mayoría de las veces las cuentas salen igual y la corrida sale VERDE sobre un
esquema que ya no es suyo.

Por eso, **cuando quien arranca es una suite** (`make frameworks-test-*`, o `pytest` dentro de la
carpeta de la demo), el nombre lleva además la sesión: `flask_demo` pasa a ser
`flask_demo__s41287`, y en SQLite el fichero pasa a ser `flask__s41287.sqlite`. Sale del PID, así
que **no hay que exportar nada**; la suite borra su base al terminar, y lo que deje una corrida que
reviente lo recoge el barrido con el que arranca `uv run pytest`.

**Los servidores de desarrollo no lo llevan.** `make flask-dev`, `make seed` y un `psql` a mano ven
exactamente `flask_demo`, la base que sembraste. La regla es `SNAKEORM_SESSION_ID`: si está puesta se
añade, y si no, no. Ponla a mano (`SNAKEORM_SESSION_ID=spike`) para fijar una base entre varias
corridas — con el matiz de que un identificador escrito a mano no se barre nunca, porque solo un PID
se puede dar por muerto.

## Arrancar

```bash
uv sync --group test-frameworks   # instala django/flask/fastapi (una vez)

make django-dev      # http://127.0.0.1:8080  (SSR + API)
make flask-dev       # http://127.0.0.1:5000  (SSR + API)
make fastapi-dev     # http://127.0.0.1:8001  (solo API)

make frameworks-test # corre la verificación de las tres
```

Cada carpeta tiene su propio `README.md` con sus rutas/endpoints y qué demuestra.
