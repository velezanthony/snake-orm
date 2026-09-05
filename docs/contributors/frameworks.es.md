# Trabajar en las demos

```bash
make frameworks-test          # the four suites: shared, FastAPI, Flask, Django
make typecheck-frameworks     # mypy over shared/ (from `frameworks/`, where `shared` resolves)
```

Las dos órdenes dan por hecho el repositorio montado: ver [Montar el entorno](development.es.md).

`frameworks/` tiene **cuatro presentaciones de UNA sola capa de dominio**, y la cuarta no es Python:

| Demo | Qué sirve | Se arranca con |
|---|---|---|
| `frameworks/django/` | páginas HTML **y** JSON en `/api/` | `make django-dev` (:8080) |
| `frameworks/flask/` | páginas HTML **y** JSON en `/api/` | `make flask-dev` (:5000) |
| `frameworks/fastapi/` | solo JSON en `/api/`, sobre un `AsyncSession` | `make fastapi-dev` (:8001) |
| `frameworks/react_front/` | las mismas páginas, pintadas en el navegador contra cualquiera de las tres APIs | `npm run dev` (:5173) |

Existen para que "¿cómo hago esto en mi framework?" tenga respuesta leyéndolas en paralelo — y eso
solo funciona si contestan las mismas preguntas. Hay varios tests que las mantienen honestas, y están
listados al final.

**La demo de React es un CLIENTE, no un quinto dominio**: no tiene ni una consulta ni un modelo,
llama a la misma superficie `/api/`, y su selector de backend vive en `src/config/backends.ts` y en
ningún otro sitio. Es el motivo por el que que las tres APIs sean idénticas dejó de ser un detalle:
ahora hay un cliente que depende de ello. NO entra en `make frameworks-test`, que es un runner de
Python; desde Python la cubre `test_the_react_catalogue_mirrors_the_nav.py`, y del resto se encarga
`npm run typecheck`.

## La regla: un framework no lleva lógica

Todo lo que hacen las demos vive en `frameworks/shared/`, una vez. El framework parsea la petición,
llama a algo de `shared/` y pinta la respuesta. Si te ves escribiendo un `filter()` dentro de una
vista, eso pertenece a la capa de abajo.

| Capa | Qué vive ahí | Color |
|---|---|---|
| `shared/models/` | las clases `@snake_model`, el grafo entero | ninguno |
| `shared/selectors/` | **fragmentos** que CONSTRUYEN un `SnakeQuery` sin ejecutarlo, más ejecutores finos | los fragmentos, ninguno |
| `shared/services/` | las escrituras: `session.add`, `update`, `upsert`, `delete` | síncrono |
| `shared/usecases/` | validar, buscar, decidir, escribir y **commitear una vez** | síncrono |
| `shared/aio/` | el gemelo asíncrono de `usecases/` | asíncrono |
| `shared/viewmodels/` | convierte filas en lo que una plantilla pinta | síncrono |
| `shared/dto/` | convierte filas en diccionarios serializables a JSON | ninguno |
| `shared/web/` | `nav.py`: las secciones de la barra lateral que comparten las demos | ninguno |
| `shared/data/` | el sembrador detrás de `make seed FW=… SCALE=…` | síncrono |
| `shared/migrations/` | el historial de migraciones, **una vez**, con un `<dominio>/` por dominio | ninguno |
| `shared/static/` | el CSS y el JS que sirven las dos demos SSR | ninguno |
| `shared/auth.py` | hasheo y verificación de contraseñas | ninguno |

**Las migraciones viven en `shared/` y cada app las ENLAZA con un symlink.**
`django/apps/orders/migrations`, `flask/apps/orders/migrations` y `fastapi/apps/orders/migrations`
son enlaces a `shared/migrations/orders`, así que las tres demos reproducen el MISMO historial
fichero a fichero. Antes eran tres copias, que es un esquema que puede derivar entre demos
construidas sobre un único dominio — y una deriva que `make frameworks-test` solo encontraría en el
motor que le tocara tocar.

**Un fragmento no tiene color, y ésa es toda la costura.** Construir SQL no ejecuta nada, así que un
`SnakeQuery` se le puede dar a cualquiera de las dos sesiones. Escribe la consulta una vez como
fragmento y los dos caminos ejecutan el mismo objeto — por eso su SQL es idéntico por construcción y
no por acuerdo.

```python
# shared/selectors/orders_selectors.py — a FRAGMENT: it builds, it does not run
def order_by_id(order_id: int) -> SnakeQuery[Order]:
    """FRAGMENT: one order by id, bare, NOT executed. What a WRITE path wants."""
    return SnakeQuery(Order).filter(Order.id == order_id)
```

Lo que sí se escribe dos veces es el control flow, porque `await` es sintaxis y un mismo cuerpo no
puede servir a los dos colores. Es la única duplicación de la capa, y dos redes sostienen las copias:
`test_async_mirror.py` (mismos nombres, mismos parámetros) y `test_sync_async_parity.py` (misma
respuesta, mismo SQL, mismo mensaje).

## Definir un endpoint

### La API: el VERBO lleva la acción, la ruta nombra el recurso

Los tres declaran el método en la ruta.

```python
# FastAPI — apps/orders/urls.py
router = APIRouter(prefix="/api/orders", tags=["orders"])

@router.post("/{order_id}/reserve")
async def reserve(order_id: int, session: SessionDep) -> dict[str, object]:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = await usecases.reserve(session, order_id=order_id)
    if isinstance(result, Failure):
        raise http_error(result)
    return order_dict(result)
```

```python
# Flask — apps/orders/api.py
orders = Blueprint("orders-api", __name__, url_prefix="/api/orders")

@orders.post("/<int:order_id>/reserve")
def reserve(order_id: int) -> ResponseReturnValue:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = usecases.reserve(g.session, order_id=order_id)
    if isinstance(result, usecases.Failure):
        abort(FAILURE_STATUS[result.reason])
    return jsonify(order_dict(result))
```

```python
# Django — apps/orders/api.py, routed from apps/orders/urls.py
@api_view(["POST"])
def reserve(request: Request, order_id: int) -> Response:
    """Takes a DRAFT order to RESERVED, holding its units under a ROW LOCK."""
    result = usecases.reserve(_session(request), order_id=order_id)
    return _refused(result) or Response(order_dict(result))
```

Tres cosas son iguales en los tres, y son la convención:

- **El nombre del blueprint lleva `-api`** cuando el dominio también tiene páginas (`orders` frente a
  `orders-api`), porque dos blueprints no pueden compartir un nombre de `url_for`.
- **Un `Failure` se convierte en estado por `FAILURE_STATUS`**, nunca en un número puesto a mano. Esa
  tabla es el único sitio donde se decide `missing_fields` → 400, `not_found` → 404, `conflict` → 409
  y `payment_declined` → 402.
- **Cero consultas y cero `commit`** en el router. La transacción es del caso de uso.

**En Django una URL resuelve a UNA vista**, así que un recurso que contesta a dos verbos es una vista
que despacha por método — la colección GET+POST, el elemento GET+DELETE. Lo que no puede pasar es una
URL por verbo, porque entonces `/api/orders` deja de ser el recurso.

**La colección canónica de Django termina en barra.** `APPEND_SLASH` redirige un GET a ella pero se
NIEGA a hacerlo con un POST, y dice por qué: un 301 no puede llevar cuerpo, así que redirigir dejaría
caer en silencio el pedido que alguien acaba de hacer. Django prefiere gritar a perderlo. Flask y
FastAPI sirven `/api/orders`; Django sirve `/api/orders/`; la red de paridad compara operaciones, así
que una barra entre tres routers no es deriva.

### SSR: la RUTA lleva la acción, el verbo solo dice "enseña" o "hazlo"

Y esto no es una elección de estilo. **Un `<form>` de navegador sabe emitir GET y POST y nada más** —
ni PUT ni DELETE. Así que un borrado no puede ser `DELETE /orders/<id>`; es una ruta que dice
"delete":

```
GET  /orders/delete/<id>    the confirmation page
POST /orders/delete/<id>    performs it
```

Todas las páginas de las dos demos SSR siguen esa forma, y ninguna usa otro verbo que GET y POST.

```python
# Flask — the verb is declared where the route is
@orders.get("/update/<int:order_id>")
def edit_order_form(order_id: int) -> ResponseReturnValue: ...

@orders.post("/update/<int:order_id>")
def update_order(order_id: int) -> ResponseReturnValue: ...
```

```python
# Django — the route does not say the verb; the view does
path("update/<int:order_id>/", views.order_update, name="orders_update")

@require_POST
def order_update(request: HttpRequest, order_id: int) -> HttpResponse: ...
```

Esa asimetría es la convención de cada framework y no una inconsistencia, y tiene una consecuencia
que conviene saber: el lector de rutas de `shared/tests/routes.py` no puede sacar el verbo de un
urlconf de Django, porque ahí no está.

**Una página LEE por un view model y ESCRIBE por un caso de uso.** El view model es lo que convierte
filas en algo que una plantilla pinta, y llama al caso de uso por debajo — así que una página alcanza
más operaciones de las que su fichero de vistas parece llamar.

## Autenticación: ni `django.contrib.auth` ni `flask-login`

Las dos demos SSR hacen lo mismo, y es una decisión, no un olvido:

```python
# The framework's signed cookie holds only the id...
session["user_id"] = user.id           # Flask
request.session["user_id"] = user.id   # Django

# ...and the USER comes from SnakeORM
current_user = selectors.get_user(orm_session, user_id)
```

`django.contrib.auth` exige el **modelo** `User` de Django y sus migraciones, así que adoptarlo
metería un segundo ORM en una demo cuyo objetivo entero es que los datos sean de SnakeORM.
`flask-login` sí funcionaría sobre cualquier ORM, pero cogerlo dejaría asimétricas a las dos demos
SSR, porque Django no puede seguirlo por lo de arriba.

Así que las dos usan lo más bajo que ambos frameworks traen de serie —la cookie de sesión firmada— y
resuelven el usuario por SnakeORM. Django pone `SESSION_ENGINE` en `signed_cookies` por el mismo
motivo: la tabla de sesiones en base de datos es del ORM de Django.

La mitad de la API es distinta y a propósito: `auth.issue_token` y `auth.revoke_token` existen solo
ahí, porque un token es para un cliente que no tiene tarro de cookies.

## El CSS: dos cadenas de node, y solo una te hace falta

Hay dos `package.json` en este árbol y no comparten nada:

| | qué es | cuándo lo necesitas |
|---|---|---|
| `frameworks/package.json` | el CLI de Tailwind | solo si cambias los estilos de las demos |
| `frameworks/react_front/package.json` | Vite, TypeScript, ESLint | solo si trabajas en el cliente React |

Las dos demos SSR no necesitan NINGUNA de las dos para arrancar. Django y Flask sirven
`shared/static/app.css` —FastAPI es solo JSON, así que nunca se lo pide— y ese fichero está
versionado: node lo reconstruye, nunca se le pide nada al servir una petición. Es deliberado — quien clone esto para leer cómo un ORM mueve tres frameworks
no tiene por qué instalarse antes una cadena de JavaScript.

```bash
cd frameworks
npm install          # once
npm run build:css    # after touching shared/static/src/app.css
```

**Y LA SALIDA NO LA VIGILA NADIE, que es lo que hay que llevarse.** `app.css` es salida de build
viviendo en el índice: tocas el fuente, se te olvida reconstruir, y las dos demos SSR sirven el CSS
anterior mientras todas las puertas siguen verdes. `make audit` no lo construye y CI tampoco, así
que lo primero que se entera es una pantalla que se ve mal. Reconstrúyelo en el mismo commit que
cambia el fuente, o el cambio no está en el commit.

## Las redes que se te van a poner rojas

Ninguna necesita base de datos ni una app arrancada; leen el código de las demos con `ast`, porque
una comprobación que necesita un framework para correr es una comprobación que se salta el día que
importa. La suite del propio ORM, y lo que exigen sus puertas, está en [Testing](testing.es.md).

| Red | Qué sostiene |
|---|---|
| `test_the_demos_serve_the_same_routes.py` | las páginas de Django son las de Flask; las tres APIs son iguales |
| `test_the_pages_and_the_api_do_the_same_things.py` | una ESCRITURA alcanzable desde una sola superficie está nombrada, con su motivo |
| `test_async_mirror.py` | un dominio gemelado en `shared/aio/` está gemelado ENTERO |
| `test_sync_async_parity.py` | los dos colores dan la misma respuesta, el mismo SQL y los mismos avisos |
| `test_selectors_and_services.py` | cada selector y cada servicio se ejercita al menos una vez |
| `test_the_page_and_the_api_reach_one_usecase.py` | DENTRO de una demo, `/orders` y `/api/orders` caen en el mismo caso de uso |
| `test_nav_is_wired_in_both_demos.py` | cada sección del menú es un enlace que las dos demos saben resolver |
| `test_demo_templates_match.py` | las dos demos SSR colocan sus plantillas igual, fichero a fichero |
| `test_the_react_catalogue_mirrors_the_nav.py` | la barra lateral de React dice lo que dice `shared/web/nav.py` |
| `test_the_session_says_what_the_engine_cannot_do.py` | la sesión anuncia cada salvedad de la que la demo depende |

Las dos primeras son los dos EJES y la pareja es justo el objetivo: la red de tres columnas compara
frameworks EN HORIZONTAL, y tres apps pueden derivar igual y seguir coincidiendo entre ellas. La red
del caso de uso único es el eje vertical: dentro de una sola app, ¿decide la página lo que decide el
endpoint? Si no, la demo ha dejado de ser un BFF.

Dos de ellas llevan catálogos de exenciones —`_SSR_SPELLINGS`, `_NOT_A_DOMAIN_ENDPOINT` y `_OWED` en
la red de rutas, `_WRITE_ON_ONE_SURFACE` y `_API_ONLY` en la de superficies— y cada entrada lleva
**por qué**. Ahí viven dos clases de motivo y distinguirlas es el
objetivo: una DECISIÓN, y una brecha que simplemente NO ESTÁ AUDITADA, que lo dice con esas palabras.
Una justificación que no tienes es peor que ninguna, porque cierra la pregunta. Cada catálogo tiene
además un test que borra la entrada el día que deja de aplicar.

## Añadir un dominio

1. Modelos en `shared/models/`, enlazados con `snake_link()`.
2. Sus migraciones en `shared/migrations/<dominio>/`, y un **symlink** a ese directorio desde el
   `apps/<dominio>/migrations` de cada app. Un historial, tres demos.
3. Fragmentos en `shared/selectors/` — construye la consulta, no la ejecutes.
4. Escrituras en `shared/services/`, orquestación en `shared/usecases/` con **un** commit.
5. Si FastAPI lo va a servir, su gemelo en `shared/aio/` — **entero**, o la red del espejo falla.
6. `shared/dto/` para JSON, `shared/viewmodels/` para plantillas.
7. Los routers: `apps/<dominio>/urls.py` en FastAPI, `apps/<dominio>/api.py` en Flask y Django,
   `apps/<dominio>/web_urls.py` para las páginas de Django y `apps/<dominio>/urls.py` para las de
   Flask.
8. Registra: `include_router` en el `main.py` de FastAPI, `register_blueprint` en el `app.py` de
   Flask, `include()` en el `config/urls.py` de Django.
9. La barra lateral: una `NavSection` en `shared/web/nav.py:SECTIONS`, más su ruta en
   `flask/apps/nav.py:ENDPOINTS` y `django/apps/nav.py:_URL_NAMES`. Si te lo saltas,
   `test_nav_is_wired_in_both_demos.py` se pone rojo.
10. `make frameworks-test`, y lee lo que los catálogos te pidan escribir.
