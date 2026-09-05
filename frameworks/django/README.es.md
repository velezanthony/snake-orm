# SnakeORM · demo Django (SSR + API JSON)

App de demostración **Django** sobre **SnakeORM**, montada sobre el dominio compartido de
`frameworks/shared/`: diez dominios y 29 tablas. Django aquí es SOLO la capa web; la persistencia,
el esquema y las migraciones los lleva SnakeORM.

> **No se usa el ORM de Django** para los datos de negocio: no hay `models.Model`, ni
> `makemigrations`, ni tablas de Django. Los modelos viven en `frameworks/shared/models/` y se
> comparten con las demos de Flask y FastAPI. La **sesión de login va en una cookie firmada**
> (`signed_cookies`): tampoco hay tabla de sesiones en base de datos.

## Qué demuestra

- **La misma pregunta contestada por tres frameworks.** Las vistas son finas: leen el request, llaman
  a un caso de uso de `shared/` con parámetros planos y traducen el resultado a una respuesta.
- **Una plantilla no navega una relación.** Todo lo que pinta sale de `shared/viewmodels/`, que
  devuelve dicts planos de primitivas. Una plantilla que recorriera `post.author.username` estaría
  cargando una relación en la capa de presentación, donde ningún `assert_queries` mira.
- **Un post ajeno contesta 404, no 403**, igual que en Flask. Un 403 CONFIRMA que el post existe, que
  es justo el dato que quien pregunta no tenía.
- **El lateral sale de un catálogo, no de una lista escrita a mano.** `shared/web/nav.py` dice qué
  secciones hay; `apps/nav.py` las convierte en enlaces con `reverse()`. El catálogo no guarda una
  sola URL: Django resuelve por nombre de ruta y Flask por endpoint, y un path escrito en el catálogo
  sería una tercera respuesta que nadie ejecuta.

## Base compartida (`frameworks/shared/`)

La app **no redefine** modelos ni datos: los importa. `frameworks/` se añade a `sys.path` (en
`config/settings.py`, `manage.py` y `verify.py`).

| Import | Qué aporta |
|---|---|
| `from shared.models import ...` | Los modelos SnakeORM de los diez dominios (`snake_link()` ya llamado ahí). |
| `from shared.data import seed, demo_scale` | El seeder por FACTORÍA: la escala la fija `DEMO_SCALE`. |
| `from shared.viewmodels import ...` | La forma plana que lee una plantilla. |
| `from shared.usecases import ...` | La operación completa de cada acción, escrita una vez. |
| `from shared import auth` | `hash_password` / `verify_password` (scrypt, solo stdlib). |
| `from shared import config` | `make_session("django")`, `drop_all("django")`, `backend()`. |

**El `.env` está en la RAÍZ del repositorio**, uno solo para el ORM y las tres demos. `DB_BACKEND`
elige `sqlite` / `postgres` / `mysql`, y `DJANGO_DB_NAME` le da a esta demo su propia base.

## Qué hay dentro

| Fichero | Rol |
|---|---|
| `apps/<dominio>/models.py`, `selectors.py`, `services.py`, `usecases.py`, `viewmodels.py` | Re-exports de `shared/`. Las vistas importan de SU capa, nunca de `shared` directamente. |
| `apps/<dominio>/web_urls.py` + `views.py` | Las páginas SSR del dominio. |
| `apps/<dominio>/urls.py` | La API JSON del dominio (bajo `/api/`). |
| `apps/<dominio>/migrations/` | El esquema, por dominio. Lo vigila `shared/tests/test_migration_drift.py`. |
| `apps/nav.py` | El context processor del lateral: `(dominio, acción)` → nombre de ruta. |
| `apps/exports.py` | La respuesta CSV en streaming, escrita una vez para inventory y orders. |
| `apps/blog/seed.py` | `drop_all` + migraciones por dominio + siembra a la escala de `DEMO_SCALE`. |
| `apps/blog/apps.py` | `ready()`: reset + seed al arrancar (idempotente por reset). |
| `apps/blog/middleware.py` | `SnakeSessionMiddleware`: UNA sesión SnakeORM por request. |
| `apps/blog/guards.py` | Auth por cookie: `current_user()` y el decorador `login_required`. |
| `templates/` | UN árbol para todas las páginas: `layout/`, y un directorio por dominio. |
| `apps/*/tests.py` | Verificación con `django.test.Client`, sin levantar servidor. |
| `verify.py` | Corre `apps` entero. Corría solo `apps.blog`, y las suites de los otros dominios existían sin ejecutarse nunca. |

## Rutas SSR

Django conserva la barra final en todas sus rutas; Flask no la pone. Es una diferencia deliberada
entre las dos demos, no una inconsistencia.

### Auth (`apps/auth/web_urls.py`)

| Método | Ruta | Qué hace |
|---|---|---|
| GET/POST | `/auth/register/` | Alta de user (username/email únicos, password hasheada). |
| GET/POST | `/auth/login/` | Acceso: `verify_password` y guarda `user_id` en la cookie firmada. |
| POST | `/auth/logout/` | Limpia la sesión. |

### Blog (`apps/blog/urls.py`) — las únicas páginas con login

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/` | Lista de posts con su autor (`include` → 1 JOIN, sin N+1). |
| GET/POST | `/posts/new/` | Crea un post (`author_id` = user logueado). |
| GET | `/posts/<id>/` | Detalle de un post. |
| GET/POST | `/posts/<id>/edit/` | Edita un post. **Solo el autor** (si no, 404). |
| GET/POST | `/posts/<id>/delete/` | Borra un post. **Solo el autor** (si no, 404). |

### Inventory (`apps/inventory/web_urls.py`) — la clave es un PAR

El stock se identifica por `(warehouse_id, sku_id)`, así que la clave viaja en la URL en dos mitades.
Estas páginas NO piden login: el stock no tiene dueño, y una puerta ahí no guardaría nada.

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/inventory/list/` | Stock con `include` de warehouse y sku, filtro `?warehouse=` y pager real. |
| GET | `/inventory/detail/<warehouse_id>/<sku_id>/` | El par, sus dos to-one aplanados y sus movimientos. |
| GET/POST | `/inventory/create/` | Recuento físico (UPSERT): el par lo elige el formulario. |
| GET/POST | `/inventory/update/<warehouse_id>/<sku_id>/` | Corrige los niveles; los dos selects de la clave van `disabled`. |
| GET/POST | `/inventory/delete/<warehouse_id>/<sku_id>/` | Confirmación; con historial contesta 409 y lo explica. |
| GET | `/inventory/report/` | `annotate`, `GROUP BY` + `HAVING`, una función de ventana y un `join` + `distinct`. |
| GET | `/inventory/export/` | CSV **en streaming** con `session.iterate()`. |

### Orders (`apps/orders/web_urls.py`) — el dominio con operaciones

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/orders/list/` | Pedidos paginados, filtro por estado. |
| GET | `/orders/detail/<id>/` | El pedido, sus líneas y su factura si la tiene. |
| GET/POST | `/orders/create/`, `/orders/update/<id>/`, `/orders/delete/<id>/` | El CRUD. |
| GET | `/orders/report/` | Agregados, ventana y un `union` con `LIMIT` por rama. |
| GET | `/orders/export/` | CSV en streaming de las líneas. |
| GET | `/orders/operate/` | El elector: los pedidos desde los que se puede operar. |
| GET | `/orders/operate/<id>/` | Qué stock hay para cada línea, y qué operación se ofrece. |
| POST | `/orders/operate/<id>/reserve/` | Bloquea las filas de stock con `for_update` y promete las unidades. |
| POST | `/orders/operate/<id>/settle/` | Factura, cobra y envía; si el cobro se cae, un `savepoint` rebobina sin perder la factura. |
| POST | `/orders/operate/<id>/cancel/` | Devuelve las unidades si estaban reservadas. |

> **Las tres operaciones declaran su nivel de aislamiento**, y `SET TRANSACTION` solo vale como
> PRIMERA sentencia de la transacción. Por eso sus handlers no leen NADA antes de llamar: hacen
> `session.rollback()` justo antes, con el motivo escrito al lado. Quitarlo no rompe nada en Postgres
> —el nivel por defecto coincide con el que pide la operación, así que se acepta en silencio— y es
> fatal en MySQL, que viene en `REPEATABLE READ`.

### Billing (`apps/billing/web_urls.py`)

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/billing/list/` | Facturas paginadas, filtro pagada/abierta. |
| GET | `/billing/detail/<invoice_id>/` | La factura, sus pagos y lo que queda por cobrar. |
| GET | `/billing/report/` | `annotate`, y `GROUP BY` + `HAVING` sobre céntimos ENTEROS. |

No tiene `create`/`update`/`delete`, y es diseño: una factura no se edita a mano. `shared/tests/test_nav.py`
aserta esa ausencia.

### Lab (`apps/lab/urls.py`)

`/lab/`, `/lab/aggregates`, `/lab/subqueries`, `/lab/joins`, `/lab/pagination`, `/lab/problems`.
La última provoca un N+1 a propósito para que el panel lo señale.

## API JSON

Nueve dominios bajo `/api/`, más el esquema OpenAPI en `/api/schema/` y Swagger en `/api/docs/`.

```bash
curl 'http://127.0.0.1:8080/api/posts/' | jq .snakeorm          # bloque de debug en el JSON
curl -i 'http://127.0.0.1:8080/api/posts/'                      # cabecera Server-Timing
```

## Autenticación: sin `django.contrib.auth`, y a propósito

El login mete `user_id` en la cookie firmada (`SESSION_ENGINE = signed_cookies`) y el usuario sale de
SnakeORM. `django.contrib.auth` NO está en `INSTALLED_APPS` y no hay `AuthenticationMiddleware`.

No es un olvido: `contrib.auth` exige el **modelo** `User` de Django y sus migraciones, así que
adoptarlo metería un SEGUNDO ORM en una demo cuyo objetivo entero es que los datos sean de SnakeORM.
Lo mismo vale para la tabla de sesiones en base de datos, y por eso la sesión va en cookie firmada.

La demo de Flask hace exactamente lo mismo con la `session` de Flask y sin `flask-login`, que es lo
que mantiene las dos SSR simétricas. Está explicado entero en
[Trabajar en las demos](../../docs/contributors/frameworks.es.md).

## Sesión por request

`SnakeSessionMiddleware` (el más interno) abre `config.make_session("django")` al empezar cada
request, la cuelga en `request.snake_session`, y al terminar hace **commit** (o **rollback** si la
vista lanzó) y **close**. Va DENTRO del scope de captura de `SnakeDebugMiddleware`, así que su SQL
aparece en el panel.

**El export es la excepción, y tiene que serlo**: el middleware cierra la sesión cuando la vista
retorna, y un cuerpo en streaming se produce DESPUÉS. Así que `apps/exports.py` abre una sesión
PROPIA y la cierra en el `finally` del generador. Un generador leyendo de una sesión cerrada es el
fallo clásico de los exports en streaming.

## Debug del ORM

`SnakeDebugMiddleware` (el más externo de `MIDDLEWARE`) captura el SQL de cada request y lo entrega
según `SNAKE_ORM_DEBUG`, fijado en `settings.py` a **`ssr,envelope,timing`**:

- **`ssr`** — en las páginas SSR, inyecta el panel HTML antes de `</body>`.
- **`envelope`** — en `/api/`, añade el bloque `snakeorm` a toda respuesta JSON mientras el canal
  esté encendido, sin query param ni cabecera. Quita el canal y la respuesta va limpia.
- **`timing`** — cabecera `Server-Timing` (W3C) en todas las respuestas.

> **Seguridad — nunca en producción.** `envelope`/`sidecar` exponen SQL y parámetros. El gate los
> desactiva cuando `settings.DEBUG` es `False`. El runner de tests fuerza `DEBUG=False`, así que las
> suites restauran `DEBUG=True` con `override_settings` para ejercitar el envelope.

## Cómo correrlo

Desde `frameworks/django/`:

```bash
uv run python manage.py test apps    # verificación, sin levantar servidor
uv run python manage.py runserver 8080    # http://127.0.0.1:8080
```

Al arrancar, `ready()` recrea el esquema y siembra a la escala de `DEMO_SCALE` (`normal` por
defecto; `minimal` acelera el arranque, `large`/`massive` lo ponen a prueba). Los users sembrados son
`demo1`, `demo2`, ... y **todos comparten la contraseña `test1234`**.

## Qué verifican las suites

`apps/blog/tests.py`, `apps/inventory/tests.py`, `apps/orders/tests.py` y `apps/billing/tests.py`,
con `django.test.Client` y sin servidor:

- **Flujo completo del blog**: registro → login → crear → listar (`include` = 1 query, medido con
  `snakeorm.debug.assert_queries`) → editar → borrar → logout.
- **Aislamiento por autor**: un user no puede editar ni borrar posts de otro (404).
- **Clave compuesta**: las cinco páginas de inventory, con el par en la URL.
- **Las operaciones de orders llegan a la base**: reservar sube las unidades retenidas en la fila de
  stock de verdad, liquidar deja el pedido en `SETTLED`, cancelar las devuelve.
- **El export va en streaming**: se leen cuatro trozos del cuerpo y se comprueba que el driver
  consumió tres filas, no las trescientas veinte. Los tests del viewmodel no ven eso: solo miran el
  viewmodel, y un `list()` en la vista los dejaría a todos verdes.
- **El lateral aparece en todas las páginas** y marca la actual con `aria-current`.
- **Debug**: el panel se inyecta en el SSR, el envelope viaja en el JSON y `Server-Timing` va siempre.
