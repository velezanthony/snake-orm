# El demo de React — el mismo dominio, servido por cualquiera de las tres APIs

Las mismas páginas que sirven Django y Flask, dibujadas por un cliente que enruta en el navegador.
No es una app distinta: es una CUARTA presentación del mismo dominio, contra la misma superficie
`/api/` que ya compartían los tres demos de Python.

```bash
npm install
npm run dev          # http://localhost:5173
```

Y con la API en marcha, que es lo que este demo consume:

```bash
cd ../django && uv run python manage.py runserver 8080     # :8080
```

## Cambiar de API sin tocar una línea

El selector del topbar cambia entre **Django**, **Flask** y **FastAPI** en caliente. Toda la
decisión vive en `src/config/backends.ts` y en ningún otro sitio: los once servicios de
`src/domains/*/service.ts` piden rutas como `/api/orders` y jamás un host.

Los tres se levantan así, cada uno en su propio puerto para que puedan estar los tres a la vez — que es lo que hace útil al conmutador de la barra superior:

```bash
cd django  && uv run python manage.py runserver 8080     # :8080
cd flask   && make flask-dev                             # :5000
cd fastapi && uv run uvicorn main:app --reload --port 8001
```

Cambiar de backend **recarga la página**, y es deliberado. Cada API tiene su propia cookie de sesión,
así que el usuario logueado no viaja contigo; y las filas que hubiera en pantalla pertenecen a una
base de datos con la que la app ya no habla. Dejar el árbol montado mezclaría filas frescas con filas
rancias sin forma de distinguirlas.

## Por qué hay un proxy y no llamadas al origen

Los tres demos autentican con una cookie de sesión firmada, y los tres la marcan `HttpOnly`. Eso es
lo correcto y es justo lo que un token en `localStorage` no te da: el script de la página NO PUEDE
leerla, así que un script inyectado no puede robarla.

El precio es que un `fetch` cross-origin con `credentials: "include"` necesita que el servidor
conteste con las cabeceras CORS de credenciales. Ninguno de los tres las manda, y enseñárselas
significaría `SameSite=None` sobre http en desarrollo, que los navegadores rechazan.

Así que el dev server hace de proxy: el navegador solo habla con el origen de Vite, toda cookie es de
PRIMERA PARTE, y nada del lado Python cambia. Cada backend cuelga de su prefijo —`/backend/django`,
`/backend/flask`, `/backend/fastapi`— y el prefijo se quita al salir.

### Y el tarro de cookies va AISLADO, no solo acotado

Esto se encontró mirando, no razonando: `/api/auth/me` contestaba 401 justo después de un login
correcto, y la petición llevaba DOS cookies llamadas `sessionid` — la que había puesto el proxy y la
de otra aplicación completamente distinta corriendo en el mismo `localhost`.

`localhost` es un espacio de nombres de cookies COMPARTIDO. Cualquier proyecto de la máquina escribe
ahí, y `sessionid` es como Django llama a su sesión en todas partes: no es mala suerte, es el
resultado por defecto para cualquiera con dos proyectos Django. Acotar el `Path` no salva, porque una
cookie ya puesta en `Path=/` se manda a todo lo que cuelgue debajo.

Por eso el proxy RENOMBRA (`vite.config.ts`): las cookies de cada backend se guardan bajo un prefijo
propio, y al salir solo se reenvía ese prefijo, quitado. Los tres backends no se ven entre sí —Flask y
Starlette llaman `session` a la suya, las dos— y nada más de `localhost` las alcanza.

## Cómo está montado

El árbol va **por dominio**, espejando `django/apps/` y `flask/apps/` en vez de copiar a Angular:

| Carpeta | Qué hay | Su equivalente en Python |
|---------|---------|--------------------------|
| `src/domains/<d>/service.ts` | Habla con la API. Nadie más hace `fetch` | `api.py` |
| `src/domains/<d>/types.ts` | Lo que VUELVE. Lo que se envía va en `service.ts` | el DTO |
| `src/domains/<d>/viewmodels.ts` | Hooks que componen las lecturas y las aplanan | `viewmodels.py` |
| `src/domains/<d>/routes.tsx` | Las rutas de ESE dominio, con su prefijo | `urls.py` |
| `src/domains/<d>/pages/` | Solo pintan | los templates |
| `src/core/` | `ui/` `http/` `hooks/` `lib/` `routing/` `layout/` | `nav.py`, `session.py`, `wire.py` |
| `src/config/` | `backends.ts`, el registro de rutas y el router raíz | `config/settings.py` + `config/urls.py` |

Los nombres van pelados dentro del dominio —`service.ts`, no `orders.service.ts`— por la regla que el
propio repositorio ya aplica: dentro de `apps/orders/` el fichero se llama `urls.py`, y dentro de
`shared/usecases/` se llama `orders_usecases.py`. **El nombre lleva lo que la carpeta no dice.**

La UI va por nivel atómico, y cada nivel tiene alias propio: `@atoms/Button`, `@molecules/Card`,
`@organisms/DataTable`. No es para escribir menos — es que el alias DICE de qué nivel es una pieza en
el punto de uso. Y el alias es la ÚNICA forma de importarla: permitir además `~/core/ui/atoms/Button`
serían dos nombres para un módulo.

**Sin `lazy` en las rutas**, y es una decisión: partir el bundle por ruta compra una descarga inicial
menor y la paga con un spinner la primera vez que entras en cada sección. Esto se lee de punta a punta
en localhost, donde la descarga es gratis y el spinner es lo único que se nota.

**Los componentes de `ui/` NO sustituyen al CSS**: lo envuelven. `shared/static/src/app.css` ya hizo
la mitad difícil con `@apply` —`.btn`, `.card`, `.badge` son componentes, no utilidades sueltas—, y
escribir `className="btn btn-primary btn-md"` en veinte sitios tiraría esa capa a la basura un piso
más arriba. Como prop tipada es un conjunto cerrado: `variant="primry"` no dibuja un botón sin estilo,
no compila.

## La red que impide que el catálogo se desvíe

`shared/web/nav.py` dice qué secciones hay y qué páginas cuelgan de cada una, sin una sola URL.
Cada dominio lo repite en su `routes.tsx` añadiendo la ruta de cliente, porque React Router localiza
una página por path y por nada más. Eso es una CUARTA copia a mano de una lista que este repo ya sabe
que se desvía, así que hay un test que recorre las dos y falla nombrando la sección que se movió:

```bash
cd ../.. && uv run pytest frameworks/shared/tests/test_the_react_catalogue_mirrors_the_nav.py -q
```

## Una ruta se escribe una vez

`href("orders.detail", { orderId: 7 })` es la única forma en que este cliente escribe una URL. React
Router trae un `href()` que hace lo mismo y no sirve aquí —existe solo en framework mode y esto es
una SPA—, así que se construye sobre el registro que los dominios ya declaran.

Lo que compra son cinco cosas que **no compilan**:

```ts
href("orders.detial", { orderId: 7 })       // nombre inexistente
href("orders.detail", { id: 7 })            // el parámetro se llama orderId
href("orders.list", { orderId: 7 })         // esa ruta no lleva parámetros
href("inventory.pair", { warehouseId: 1 })  // media clave compuesta no es una clave
href("orders.detail")                       // falta el objeto entero
```

Ninguna es cazable en una plantilla de cadena. `src/core/routing/routing.types.test.tsx` las fija con
`@ts-expect-error`, y el runner es `tsc`: si alguna empieza a compilar, la build se pone roja.
