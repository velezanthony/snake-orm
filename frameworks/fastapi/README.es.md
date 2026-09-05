# SnakeORM · demo FastAPI (solo API JSON)

App de demostración **solo API JSON** (nada de SSR) sobre **SnakeORM**, montada sobre el dominio
compartido de `frameworks/shared/`: diez dominios y 29 tablas. Es la demo **ASÍNCRONA** de las tres,
y eso no es un detalle de implementación: es lo que viene a demostrar.

## Por qué esta demo existe

FastAPI **es** ASGI: un endpoint `async def` corre SOBRE el event loop, así que una llamada
bloqueante ahí no ralentiza su propia petición — para todas las demás que comparten el loop. Esta
demo estuvo mucho tiempo con endpoints `async def` y una sesión SÍNCRONA debajo, que es la peor de
las dos disposiciones: la forma de un servidor asíncrono con el comportamiento de uno que bloquea, y
nada en ningún sitio diciéndolo.

Hoy la sesión es una **`AsyncSession`** sobre un **pool** creado una vez en el `lifespan`. En async
el pool importa MÁS que en síncrono, no menos: cien tareas concurrentes sin pool son cien conexiones,
y una conexión de Postgres le cuesta memoria al servidor aunque esté parada.

## La costura: un gemelo asíncrono, no una segunda capa de dominio

Los casos de uso asíncronos viven en **`frameworks/shared/aio/`**, uno por dominio, gemelos de
`frameworks/shared/usecases/`. Lo que NO se duplica es el SQL: cada lectura es un **fragmento
`SnakeQuery` sin color** en `frameworks/shared/selectors/`, y los dos colores ejecutan el mismo
objeto. Generar SQL no ejecuta nada, así que no hay nada que pueda derivar.

Lo que sí queda duplicado es el CONTROL DE FLUJO de un caso de uso —las dos o tres líneas que
validan, deciden y confirman—, porque `await` es sintaxis y Python no deja que un cuerpo sirva a los
dos colores. **Eso es exactamente lo que vigilan dos redes**:

- `shared/tests/test_async_mirror.py` — cada gemelo cubre todos los casos de uso de su dominio. Un
  dominio medio espejado es una demo que contesta menos preguntas que las otras dos sin decirlo.
- `shared/tests/test_sync_async_parity.py` — la misma pregunta a las dos sesiones da la misma
  respuesta, el mismo SQL **y el mismo mensaje que el ORM emite sobre ese SQL**. Lo tercero no es
  celo: las dos sesiones ya derivaron una vez —la misma queja explicada con dos redacciones— y el
  test que solo miraba el SQL la dejó pasar durante meses.

### Un router sigue siendo síncrono, y está escrito

El **lab** usa `SyncSessionDep` en `apps/deps.py`. Es una página de desarrollador construida sobre
`shared/selectors/catalog.py`: quince lecturas escaparate que existen para enseñar la superficie de
lectura del ORM, no para servir esta API. Un gemelo asíncrono del catálogo serían quince funciones
más que mantener en paralelo con quince que no tienen un segundo llamante — justo la duplicación que
`shared/aio/` existe para evitar, no para extender.

Bloquea el loop mientras corre, y ése es el coste honesto de la decisión. Lo que NO se hizo fue
quitar el router de la demo para que la cifra quedara limpia.

## Estructura

```
frameworks/fastapi/
├── main.py                 # la app: lifespan (pool + migraciones + siembra), routers, debug
├── apps/deps.py            # la sesión por request: AsyncSession, y SyncSessionDep para el lab
├── apps/<dominio>/         # urls.py (router) + re-exports de shared/ o de shared/aio/
├── apps/<dominio>/migrations/
└── tests/
```

`frameworks/` se añade a `sys.path` para importar `shared`.

## Base de datos

**El `.env` está en la RAÍZ del repositorio**, uno solo para el ORM y las tres demos. `DB_BACKEND`
elige `sqlite` / `postgres` / `mysql`; `FASTAPI_DB_NAME` le da a esta demo su propia base, que se crea
sola.

**El esquema lo construyen las MIGRACIONES por dominio**, no un `init_schema`. Al arrancar, el
`lifespan` hace `config.drop_all("fastapi")`, aplica `apps/*/migrations` en orden y siembra a la
escala de `DEMO_SCALE` (`normal` por defecto). Que las migraciones y los modelos digan lo mismo lo
vigila `shared/tests/test_migration_drift.py`, en las tres demos a la vez.

> **La siembra corre sobre la sesión SÍNCRONA, a propósito.** Arrancar no es servir: todavía no hay
> nada compitiendo por el loop, y el seeder es el mismo código de dominio que corren las otras dos
> demos. Hacerlo asíncrono sería un segundo seeder que mantener en paralelo sin ganar nada.

## Rutas

Once routers bajo `/api/`: `accounts`, `auth`, `billing`, `blog`, `content`, `engagement`,
`inventory`, `logistics`, `orders`, `taxonomy` y `lab`. Son los diez dominios más el `lab`, y la
cuenta sale de `main.py` —de los `include_router`— y no de la memoria de nadie: la línea decía nueve
y `orders` ya llevaba tiempo montado. El esquema OpenAPI está en `/openapi.json` y la documentación
interactiva en `/docs`.

El blog añade **autenticación por cookie firmada** (`SessionMiddleware` de Starlette, secreto en
`DEMO_SECRET_KEY`) y un CRUD donde cada user gestiona solo sus posts: sin sesión, 401.

Los users sembrados son `demo1`, `demo2`, ... y **todos comparten la contraseña `test1234`**.

## Cómo correrlo

```bash
cd frameworks/fastapi
uv run uvicorn main:app --reload --port 8001   # http://127.0.0.1:8001 · docs en /docs
uv run pytest                      # verificación con TestClient, sin servidor
```

## Debug del ORM

El middleware se enchufa en una línea (solo API, así que sin canal `ssr`):

```python
os.environ.setdefault("SNAKE_ORM_DEBUG", "envelope,timing,sidecar")  # antes de crear la app
app.add_middleware(SnakeDebugASGI, production=False)
```

- **`envelope`** — con el canal encendido, toda respuesta JSON trae un bloque `snakeorm` con el
  resumen y cada query, sin query param ni cabecera. A un objeto se le añade de clave hermana; un
  array se envuelve bajo `{data, snakeorm}`.
- **`timing`** — cabecera W3C `Server-Timing` en todas las respuestas, incluido un 401.
- **`sidecar`** — cada respuesta trae `X-Debug-Token`; el panel HTML se sirve en `/__snake__/{token}`.

En `production=True` los canales que exponen SQL caen solos.

## Qué verifican las suites

- `tests/test_demo.py` — el flujo completo del blog: registro → login → crear → listar → editar →
  borrar → logout, con el CRUD cerrado (401) antes de login y tras logout; el `password_hash` no se
  filtra nunca; el `include` no dispara N+1 (`assert_queries(1)`); y los tres canales de debug.
- `tests/test_inventory.py` — el dominio de la clave compuesta, por HTTP.
- `tests/test_every_router_answers.py` — **recorre las 36 rutas GET que la app declara en su propio
  OpenAPI y exige que ninguna conteste 5xx.**

Esa última existe por un fallo medido. Cuando la demo pasó a `AsyncSession`, cuatro dominios seguían
llamando a sus casos de uso síncronos, así que `session.all(...)` les devolvía una corrutina y el
endpoint moría:

```
TypeError: 'coroutine' object is not iterable       /api/content/posts/1/revisions
RuntimeWarning: coroutine 'AsyncSession.all' was never awaited
```

Y la suite decía **18 passed** todo el rato, porque esos dieciocho tests no tocaban esos dominios.
Una cuenta que sale llena sobre un universo recortado es la forma exacta de fallo contra la que este
repositorio escribe redes, y ahí estaba otra vez, un piso más arriba. La red pregunta por las rutas
al propio OpenAPI en vez de leer una lista, porque una lista hay que acordarse de ampliarla — y quien
se olvida es justo la persona para la que se escribió la comprobación.

## Qué demuestra

- El grafo de metadata de SnakeORM es **agnóstico del motor y del framework**: los MISMOS modelos de
  `shared/` corren aquí cambiando solo Driver + Dialect.
- **La costura async es incolora**: el mismo fragmento `SnakeQuery` sirve a las dos sesiones, y la
  paridad se comprueba en la respuesta, en el SQL y en el mensaje.
- **N+1 imposible por defecto**: sin `include`, tocar `post.author` lanza `SnakeRelationshipNotLoaded` en
  vez de ir a la base a tus espaldas.
- La herramienta de debug se integra sin acoplar el núcleo al framework: `snakeorm.debug` es el
  kernel y `snakeorm.contrib.asgi` el adaptador.
