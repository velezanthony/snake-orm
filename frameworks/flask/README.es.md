# SnakeORM · demo Flask (SSR + API JSON)

App Flask que monta sobre **SnakeORM** las páginas de seis dominios —`blog`, `inventory`, `orders`,
`billing`, `taxonomy` y `logistics`— más el `lab`, y expone en JSON los diez del dominio compartido.
Todo lo que piensa vive en `frameworks/shared/`: esta app es un **envoltorio**. Una ruta parsea la
petición, llama a un caso de uso con parámetros PLANOS —nunca le pasa el `request`— y traduce el
resultado en una respuesta.

La demo de Django monta las mismas páginas y la de FastAPI el mismo JSON. Son tres envoltorios sobre
un solo dominio, y esa es la demostración entera.

## Qué demuestra

- **Base compartida, cero duplicación**: los 26 modelos, los selectores, los servicios, los casos de
  uso, los viewmodels y el catálogo del lateral viven UNA vez en `frameworks/shared/`. Esta app
  escribe su `app.py`, su `seed.py`, sus rutas y sus plantillas. Nada más.
- **Vistas finas con un mapa de fallos explícito**: el caso de uso devuelve un valor o un `Failure`,
  y la vista traduce por `reason` (`missing_fields`/`taken`/`bad_credentials` → flash + redirect al
  formulario; `not_found`/`forbidden` → 404). El caso de uso valida, orquesta y hace `commit`.
- **Un post ajeno contesta 404, no 403**, y los dos códigos están en el mismo diccionario a
  propósito: un 403 CONFIRMA que el post existe, que es justo el dato que quien pregunta no tenía
  derecho a saber. Django ya contestaba 404; Flask no, así que la misma petición recibía dos
  respuestas distintas según quién la sirviera.
- **Sin N+1**: los listados usan `include()` y las relaciones se navegan en `shared/viewmodels/`, no
  en la plantilla. Tocar una relación no incluida **lanza** en vez de disparar SQL en silencio.
- **Los CSV se escriben MIENTRAS se leen**: `apps/exports.py` sirve un `CsvExport` cuyas filas son un
  generador sobre `session.iterate()`. Y ahí hay una trampa medida: `stream_with_context` NO vale en
  Flask 3.1 —empuja los contextos de forma perezosa, así que el `teardown_app_request` ya ha cerrado
  la sesión cuando el cuerpo empieza a tirar filas—, de modo que la sesión se SACA de `g` con
  `g.pop("session")` y el stream pasa a ser su dueño. Con un `list()` en la vista todo esto sale
  verde y la página vuelve a cargarse la tabla entera en memoria antes del primer byte.
- **Las operaciones de `orders` declaran su nivel de aislamiento antes de leer**, y el hook
  `before_app_request` de esta app puede haber gastado ya la transacción antes de que el handler
  arranque. Postgres acepta la declaración en silencio cuando no cambiaría nada, así que el fallo es
  invisible en la máquina donde se escribe y fatal en MySQL.
- **Debug del ORM en una app híbrida (SSR y API) con una línea**:
  `app.wsgi_app = SnakeDebugWSGI(app.wsgi_app, channels=SNAKE.channels(), config=SNAKE.debug_config())`.
  El middleware ramifica por `Content-Type`: en HTML inyecta el panel antes de `</body>` (canal
  `ssr`); en JSON añade el bloque `snakeorm` mientras el canal `envelope` esté encendido, y **siempre**
  la cabecera `Server-Timing` (canal `timing`).

## Rutas SSR

**Sin barra final, y es deliberado.** La demo de Django monta estas mismas páginas CON barra porque
es su convención; aquí no la hay porque tampoco la escribiría un dev de Flask. Las dos demos existen
para leerse y copiarse, así que cada una se parece a lo que habría escrito su gente.

Cada dominio repite la MISMA taxonomía de páginas —`list`, `detail`, `create`, `update`, `delete`,
`report`, `export`— con la acción escrita en el path en vez de implícita en el verbo. Quien ha visto
`/inventory/list` adivina `/orders/list` antes de abrirlo.

### Auth (`apps/auth/urls.py`)

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET/POST | `/auth/register` | Alta de user (username/email únicos, password hasheada) e inicio de sesión. |
| GET/POST | `/auth/login` | `verify_password` y `user_id` en la cookie firmada; respeta `?next=`. |
| POST | `/auth/logout` | `session.clear()`. |

### Blog (`apps/blog/urls.py`) — las únicas páginas con login

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET | `/` | Redirige al listado si hay sesión, y si no al login. |
| GET | `/posts` | Listado con el autor cargado (`include` → una sola query). |
| GET/POST | `/posts/new` | Crear un post propio. |
| GET | `/posts/<id>` | Detalle con su autor. |
| GET/POST | `/posts/<id>/edit` | Editar un post propio; ajeno o inexistente → 404. |
| GET/POST | `/posts/<id>/delete` | Confirmación y borrado; ajeno o inexistente → 404. |

El `delete` tiene página de confirmación porque un GET no puede borrar nada: un enlace pelado que lo
hiciera estaría a un crawler de vaciar el blog.

### Inventory (`apps/inventory/urls.py`) — la clave es un PAR

La fila de stock la identifica `(warehouse_id, sku_id)`, así que la clave viaja en la URL en dos
mitades, tipadas `<int:...>` para que una URL con una palabra sea un 404 del router y no un
`ValueError` de la vista.

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET | `/inventory/list` | Stock con `include` de warehouse y sku, filtro `?warehouse=` y pager. |
| GET | `/inventory/detail/<warehouse_id>/<sku_id>` | El par entero, sus dos to-one aplanados y sus movimientos. |
| GET/POST | `/inventory/create` | Recuento físico (UPSERT): el par lo elige el formulario. |
| GET/POST | `/inventory/update/<warehouse_id>/<sku_id>` | Corrige los niveles; los selects de la clave van `disabled`. |
| GET/POST | `/inventory/delete/<warehouse_id>/<sku_id>` | Confirmación; con historial contesta 409 (FK RESTRICT). |
| GET | `/inventory/report` | Agregados: `annotate`, `group_by`, `having` y una función de ventana. |
| GET | `/inventory/export` | CSV en streaming de los movimientos; `?warehouse=` es OPCIONAL. |

El `export` no lleva clave en el path y su filtro viaja en la query string: acota CUÁNTO trae el
fichero, que no es lo mismo que nombrar la fila de la que va la ruta. Un enlace del lateral no lleva
nada, así que tiene que llegar al fichero entero.

### Orders (`apps/orders/urls.py`) — el dominio con operaciones

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET | `/orders/list` | Listado con el cliente y el almacén aplanados, filtro por estado y pager. |
| GET | `/orders/detail/<id>` | El pedido con sus líneas. |
| GET/POST | `/orders/create` | Alta de un pedido en borrador. |
| GET/POST | `/orders/update/<id>` | Edición del borrador. |
| GET/POST | `/orders/delete/<id>` | Confirmación y borrado. |
| GET | `/orders/report` | Agregados y un compuesto (`UNION` con `LIMIT` por rama). |
| GET | `/orders/export` | CSV en streaming de las líneas; `?state=` es opcional. |
| GET | `/orders/operate` | El SELECTOR: el listado acotado a los borradores desde los que se opera. |
| GET | `/orders/operate/<id>` | La página de la operación. |
| POST | `/orders/operate/<id>/reserve` | Reserva el stock bajo bloqueo de fila (`for_update`). |
| POST | `/orders/operate/<id>/settle` | Emite la factura y rebobina el cobro fallido a un `savepoint`. |
| POST | `/orders/operate/<id>/cancel` | Cancela y devuelve el stock. |

**`operate` son dos rutas para una acción, y el lateral es la razón.** `shared/web/nav.py` pone
`operate` en el menú, y un enlace del lateral no lleva id: así que `/orders/operate` a secas tiene
que contestar algo útil por sí solo, y contesta el selector.

**Las tres operaciones son rutas POST propias**, no una ruta que ramifica por el nombre de un botón.
Cada una es una transacción distinta con un mapa de fallos distinto, y un handler único tendría que
LEER el formulario para saber cuál — una lectura, justo en el camino donde una lectura es lo que no
puede pasar. Además la URL pasa a ser el nombre de lo que ocurrió, que es lo que acaban citando una
línea de log, un 405 y un redirect. Y un GET que reservara sería una operación que puede ejecutar un
crawler, un prefetch o el botón de atrás del navegador.

### Billing (`apps/billing/urls.py`) — tres páginas, y las que faltan son el argumento

| Método | Ruta | Qué hace |
|--------|------|----------|
| GET | `/billing/list` | Facturas con TRES saltos to-one aplanados por fila y sin pagar una query por ninguno. |
| GET | `/billing/detail/<invoice_id>` | La factura con sus pagos. |
| GET | `/billing/report` | Lo cobrado, lo pendiente y su reparto. |

No hay `create`, `update` ni `delete`: una factura la LEVANTA el `settle` de orders y la SALDA el
`pay_invoice`, nunca un formulario. Un formulario que dejara reescribir un importe sería la demo de
lo único que un programa de contabilidad no puede ofrecer. `shared/tests/test_nav.py` aserta esa
ausencia, así que es una decisión que el catálogo hace cumplir y no una página que nadie llegó a
escribir.

### Lab (`apps/lab/urls.py`)

`/lab/list` · `/lab/aggregates` · `/lab/subqueries` · `/lab/joins` · `/lab/pagination` ·
`/lab/problems`

La página de entrada se llama `list` y no `index`: el catálogo compartido le da a toda sección una
página `list`, así que "cada dominio tiene un listado" es un invariante y no una regla con una
excepción dentro — y una excepción es por donde se cae un enlace del lateral. `problems` provoca un
N+1 a propósito para que el panel de debug lo señale.

## API JSON

Toda la API cuelga de `/api/` por recurso, en `flask-smorest`, y está registrada en el mismo objeto
`Api`, así que TODOS los endpoints salen en el Swagger.

| Prefijo | Módulo | Qué expone |
|---------|--------|------------|
| `/api/posts`, `/api/auth` | `apps/blog/api.py` | CRUD de posts, `stats` y la sesión por cookie firmada. |
| `/api/accounts` | `apps/accounts/api.py` | Roles y los roles de un user. |
| `/api/auth` | `apps/auth/api.py` | Tokens y sesiones de un user. |
| `/api/billing` | `apps/billing/api.py` | Planes, suscripciones, facturas y cobros. |
| `/api/content` | `apps/content/api.py` | Revisiones y adjuntos de un post. |
| `/api/engagement` | `apps/engagement/api.py` | Comentarios, reacciones y visitas. |
| `/api/inventory` | `apps/inventory/api.py` | Almacenes, SKUs, stock, movimientos y reserva. |
| `/api/taxonomy` | `apps/taxonomy/api.py` | Grupos, etiquetas y las etiquetas de un post. |
| `/api/logistics` | `apps/logistics/api.py` | Depósitos, la hoja de una entrega, el tablón de salidas y la carga por hueco. |
| `/api/lab` | `apps/lab/api.py` | Los mismos experimentos del lab, en JSON. |

`/api/docs` es el Swagger UI y `/api/openapi.json` el documento. El blueprint de páginas de cada
dominio lleva el nombre PLANO (`billing`) y el de JSON el sufijo `-api` (`billing-api`): dos
blueprints no pueden compartir un nombre de `url_for`, y dos dominios ya tuvieron que recuperar el
suyo de un blueprint de API que lo estaba ocupando.

## Autenticación: sin `flask-login`, y a propósito

El login mete `user_id` en la `session` de Flask (la cookie firmada) y el usuario sale de SnakeORM.
`flask-login` no se usa, y no por desconocerlo: funcionaría sobre cualquier ORM, pero la demo de
Django NO puede seguirlo — `django.contrib.auth` exige el modelo `User` de Django y sus migraciones,
o sea un segundo ORM dentro de la demo.

Así que las dos SSR usan lo más bajo que ambos frameworks traen de serie, la cookie de sesión
firmada, y eso es lo que las mantiene simétricas. Está explicado entero en
[Trabajar en las demos](../../docs/contributors/frameworks.es.md).

## Estructura

```
frameworks/flask/
├── app.py                  # app factory: SnakeOrmConfig, blueprints, seed on boot, debug WSGI
├── apps/
│   ├── <domain>/           # accounts auth billing blog content engagement inventory lab orders taxonomy
│   │   ├── urls.py         #   páginas SSR (Blueprint con url_prefix)
│   │   ├── api.py          #   API JSON (Blueprint de flask-smorest, prefijo /api/<domain>)
│   │   ├── models.py       #   re-export de los modelos compartidos
│   │   ├── selectors.py    #   re-export de las lecturas compartidas
│   │   ├── services.py     #   re-export de las escrituras compartidas
│   │   ├── usecases.py     #   re-export de los casos de uso compartidos
│   │   ├── viewmodels.py   #   re-export de la forma plana que lee la plantilla
│   │   └── migrations/     #   el esquema del dominio, que es lo que construye la BD
│   ├── exports.py          # el CSV en streaming, escrito una vez para los dominios que exportan
│   └── nav.py              # el catálogo compartido convertido en endpoints de Flask
├── templates/
│   ├── layout/             # base.html, _sidebar.html, error.html
│   └── <domain>/<action>/  # una carpeta por página de la taxonomía
├── seed.py                 # reset + migrate + siembra a la escala DEMO_SCALE
└── verify.py               # la verificación con app.test_client() (script y pytest)
```

Un dominio tiene DOS ficheros de rutas porque tiene DOS superficies. `urls.py` son las páginas y
`api.py` el JSON; meter las dos en un módulo obligaría al registro de `app.py` a elegir cuál de las
dos mitades quiere, que es algo que no puede hacer.

El CSS es **un solo fichero compartido con Django** (`frameworks/shared/static/app.css`, servido bajo
`/static`), con vocabulario de componentes en vez de utilidades sueltas. Se construye con Tailwind
pero está commiteado: **Node hace falta para reconstruirlo, nunca para correr la demo**. El detalle
está en `frameworks/README.md`.

## Configuración y motor

El `.env` está en la **raíz del repositorio**, uno solo para el ORM y las tres demos. `DB_BACKEND`
elige `sqlite` (por defecto), `postgres` o `mysql`, y `FLASK_DB_NAME` le da a esta demo su propia
base, que se crea sola si no existe. Sin `.env` cae a SQLite (`frameworks/flask/flask.sqlite`).

Un `DB_BACKEND` desconocido **PARA**, no cae a SQLite: antes, cualquier cosa que no fuera `postgres`
acababa en un fichero local, así que un `DB_BACKEND=postgress` con una `s` de más levantaba la demo
contra otra cosa y todo parecía funcionar. La sección "Configuración" de `frameworks/README.md` tiene
el fichero entero.

**El esquema lo construyen las MIGRACIONES por dominio**, no un `init_schema`. Al arrancar,
`app.py` hace `config.drop_all("flask")`, `SNAKE.migrate()` —que aplica `apps/*/migrations` en orden
de dependencias— y siembra. `SEED_ON_BOOT=0` se salta los tres pasos.

## Users de demo

Los siembra `shared/data/factory.py` como `demo1`, `demo2`, … (uno por user de la escala). Todos
comparten la misma contraseña, `test1234` (`DEMO_PASSWORD`, en claro solo para la demo; el seeder la
hashea UNA vez y reusa el hash, salt incluido, para que sembrar a escala `massive` no cueste horas).

El volumen lo elige `DEMO_SCALE`: `minimal`, `normal` (por defecto), `large` o `massive`. La escala
fija los recuentos de las entidades primarias en `shared/data/scales.py` y el resto lo DERIVA el
factory con ratios fijos, así que todo el volumen sube o baja moviendo una constante.

## Cómo correrlo

```bash
uv sync --group test-frameworks   # una vez

make flask-dev                    # http://127.0.0.1:5000
make flask-dev SCALE=massive      # lo mismo, con la escala de estrés
make seed FW=flask SCALE=large    # sembrar sin arrancar el servidor
```

Luego, en el navegador:

- `http://127.0.0.1:5000/auth/login` — entra como `demo1` / `test1234`.
- `http://127.0.0.1:5000/posts` — listado SSR; al final aparece el **panel de debug** con el SQL que
  corrió esa página.
- `http://127.0.0.1:5000/api/posts` — JSON con el bloque `snakeorm`. Fíjate en `Server-Timing`, que
  viaja siempre.

> Los canales `envelope` y `sidecar` exponen SQL y parámetros: en producción se apagan con
> `production=True` en el middleware. Aquí está en modo desarrollo a propósito.

## Verificación (sin levantar servidor)

`verify.py` usa `app.test_client()` y son **36 tests**. Cada uno resiembra la base en un fixture
`autouse`, así que no dependen del orden.

Recorre el flujo del blog —registro → login → crear → listar (`include` = 1 query, medido con
`assert_queries`) → editar → borrar → logout— y encima comprueba lo que solo puede romper el
envoltorio:

- las páginas de `inventory` sobre la clave compuesta, **leyendo la base de vuelta** con
  `config.make_session("flask")` y no solo el HTML: que una página pinte prueba que la plantilla
  compila; lo que un envoltorio se deja es el viaje de ida y vuelta, y un formulario que devuelve
  media clave compuesta redirige a un sitio plausible igual;
- las páginas de `orders`, incluidas las tres operaciones disparadas por POST — el bloqueo de fila,
  el savepoint y el nivel de aislamiento. Ese último se comprueba pidiéndole a la sesión, desde
  DENTRO de la operación, un nivel que NO tiene ya: es la única forma del error de la que el motor
  se queja en voz alta;
- los `report` y los `export` de los dos dominios que los tienen, más las tres páginas de `billing`;
- el panel `snake-debug-panel` en el SSR y el bloque `snakeorm` + `Server-Timing` en la API.

```bash
uv run pytest frameworks/flask/verify.py -q   # 36 passed
make frameworks-test-flask                    # lo mismo, desde el Makefile
make frameworks-test                          # las cuatro suites (shared + las tres demos)
```
