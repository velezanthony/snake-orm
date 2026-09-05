# Capacidades de los motores

Qué sabe hacer cada motor, desde qué versión, y qué hace SnakeORM en su lugar cuando no puede.

Cada celda de aquí abajo está **medida contra un motor real**, no leída de un manual.

## Rango soportado

| Motor | Suelo | Techo | Versiones medidas |
|---|---|---|---|
| PostgreSQL | 15 | 18.6 | 15.18, 16.14, 17.11, 18.6 |
| MariaDB | 10.11 | 11.8 | 10.11.19, 11.4.13, 11.8.8 |
| MySQL | 8.0 | 9.7 | 8.0.46, 8.4.11, 9.7.2 |
| SQLite | 3.46.1 | 3.53.1 | 3.45.1, 3.46.1, 3.50.4, 3.53.2, 3.53.4 |

Por debajo del suelo el ORM se niega a conectar, igual que hace Django con
`minimum_database_version`: no degrada en silencio hacia un motor que nadie ha probado.

MariaDB y MySQL comparten dialecto y son **motores distintos**, con suelos distintos, como también
lo son en Django: `(10, 11)` para MariaDB, `(8, 4)` para MySQL.

## Lo importante: la versión casi nunca importa

Quince versiones de motor sondeadas. Dentro de cada familia, **todas las capacidades responden lo
mismo en todas las versiones soportadas**, con una excepción:

| Capacidad | Cambia en |
|---|---|
| `CHECK_CONSTRAINT_ADD` / `CHECK_CONSTRAINT_DROP` | **SQLite 3.53** |

Lo demás lo decide el motor y su sabor, no la versión. Por eso la matriz sigue siendo legible: una
columna por motor y un solo `Since` para el único caso que lo necesita.

## Cómo se lee la tabla

| Marca | Significado |
|---|---|
| `Full` | el motor lo hace de forma nativa |
| `≥ x.y` | lo hace a partir de esa versión; por debajo, degrada |
| `Degr` | no lo hace; SnakeORM pone algo en su lugar y lo dice |
| `Nope` | no lo hace y no hay sustituto; el ORM se niega en tiempo de compilación |

## La matriz

| Capacidad | SQLite | MariaDB | MySQL | Postgres | En qué degrada |
|---|---|---|---|---|---|
| `RETURNING` | Full | **Full** | Nope | Full | `lastrowid` y un viaje de ida y vuelta de más |
| `ROW_CONSTRUCTOR` | Full | Full | Full | Full | — |
| `TRANSACTIONAL_DDL` | Full | Nope | Nope | Full | nada: una migración de N pasos deja de ser todo o nada |
| `UPSERT` | Full | Full | Full | Full | — |
| `PARTIAL_INDEXES` | Full | Nope | Nope | Full | índice sobre la tabla ENTERA |
| `TEXT_IN_PRIMARY_KEY` | Full | Nope | Nope | Full | nada: necesita `max_length` para volverse VARCHAR |
| `CHECK_CONSTRAINT_DDL` | **≥ 3.53** | Full | Full | Full | rehacer la tabla |
| `ADD_CONSTRAINT` | Nope | Full | Full | Full | las FK van dentro del `CREATE TABLE`, tablas en orden topológico |
| `ALTER_COLUMN` | Nope | Full | Full | Full | rehacer la tabla |
| `SET_ISOLATION` | Nope | Full | Full | Full | nada: un solo escritor a la vez ya es serializable |
| `ROW_LOCKING` | Nope | Full | Full | Full | nada: SQLite bloquea el fichero entero |
| `SCHEMAS` | Nope | Nope | Nope | Full | nada: allí un «schema» ES una base de datos |
| `STORED_FUNCTIONS` | Nope | **Full** | Nope | Full | nada. Los dos tienen `CREATE FUNCTION`; solo MariaDB puede REEMPLAZARLA |
| `REPLACE_VIEW` | Nope | Full | Full | Full | `DROP` + `CREATE` |
| `PARENTHESISED_COMPOUND` | Nope | Full | Full | Full | nada: un `LIMIT` no se puede confinar a una rama |
| `CTE_IN_COMPOUND_BRANCH` | Nope | Nope | **Full** | Full | nada: la recursión va suelta |
| `INDEX_METHODS` | Nope | Degr | Degr | Full | solo BTREE/HASH, sin GIN/GIST/BRIN |
| `DROP_COLUMN_CASCADES_FK` | Nope | Nope | Nope | Full | quitar antes la clave, o rehacer la tabla |
| `COMMENTS` | Nope | Degr | Degr | Full | cláusula en `CREATE`/`ALTER TABLE`, no `COMMENT ON` |
| `ILIKE` | Degr | Degr | Degr | Full | `LOWER(a) LIKE LOWER(b)` |
| `JSON` | Degr | Degr | Degr | Full | TEXT (SQLite) / JSON sin JSONB (MySQL) |
| `UUID` | Degr | **Full** | Degr | Full | SQLite: TEXT. MySQL: `CHAR(36)`. MariaDB tiene el tipo |
| `BOOLEAN` | Degr | Degr | Degr | Full | `INTEGER` 0/1 / `TINYINT(1)` |
| `ARRAYS` | Degr | Degr | Degr | Full | JSON en TEXT; ni se consulta dentro ni se indexa |
| `DECIMAL_ORDERING` | Degr | Full | Full | Full | TEXT: `'10.00'` ordena antes que `'9.99'` |
| `TIMESTAMPTZ` | Degr | Degr | Degr | Full | TEXT ISO-8601; la zona viaja dentro del texto |
| `INTERVAL` | Degr | Degr | Degr | Full | TEXT; no comparable como duración |
| `CALENDAR_INTERVAL` | Degr | Full | Full | Full | los meses desbordan en vez de ajustarse a fin de mes |
| `INT_WIDTHS` | Degr | Full | Full | Full | un solo `INTEGER`: el rango no se comprueba |
| `FLOAT_SPECIALS` | Degr | Degr | Degr | Full | `NaN` vuelve NULL (SQLite) / no se puede guardar (MySQL) |

## MariaDB no es MySQL

El dialecto sirve a los dos y declara **una** respuesta. Medidos, difieren en cuatro capacidades, y
en las cuatro la declaración sigue a MySQL, así que MariaDB paga una limitación que no tiene:

| Capacidad | MariaDB 10.11 / 11.4 / 11.8 | MySQL 8.0 / 8.4 / 9.7 | Declarado |
|---|---|---|---|
| `RETURNING` | **sí** — responde `((1, 7),)` | no — `1064` | `Nope` **(falso para MariaDB)** |
| `UUID` | **tipo nativo, y valida** — basura da `1292` | no existe el tipo | `Degraded` **(falso para MariaDB)** |
| `STORED_FUNCTIONS` | **sí** — `CREATE OR REPLACE FUNCTION` | `CREATE FUNCTION` sí, **`OR REPLACE` no** | `Nope` **(falso para MariaDB)** |
| `CTE_IN_COMPOUND_BRANCH` | no — `1064` | **sí** | `Nope` (falso para MySQL) |

Tres le cuestan funcionalidad real a MariaDB; la cuarta se la cuesta a MySQL. Ninguna varía por
versión: son diferencias de sabor, estables en todo el rango soportado.

## Qué cambió en SQLite 3.53

| Sentencia | 3.45.1 | 3.46.1 | 3.50.4 | 3.53.2 | 3.53.4 |
|---|---|---|---|---|---|
| `ALTER TABLE … ADD CONSTRAINT … CHECK` | no | no | no | **sí** | **sí** |
| `ALTER TABLE … DROP CONSTRAINT` | no | no | no | **sí** | **sí** |
| `ALTER TABLE … ADD CONSTRAINT … UNIQUE` | no | no | no | no | no |
| `ALTER TABLE … ADD CONSTRAINT … PRIMARY KEY` | no | no | no | no | no |
| `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` | no | no | no | no | no |
| `ALTER TABLE … ALTER COLUMN` | no | no | no | no | no |

Por eso el CHECK se separó y el resto siguió junto: 3.53 habilitó una de las cuatro.

Debian 13 trae SQLite 3.46.1 y Ubuntu 24.04 trae 3.45.1, así que **el camino degradado es el normal
durante años** y el nativo es la excepción. Ojo: el build de Python 3.12 de `uv` enlaza SQLite
3.45.1, por debajo del suelo de este proyecto.

## Tipos de SQLite, sondeados por comportamiento

En SQLite **declarar un tipo nunca falla**: un nombre desconocido cae a afinidad TEXT, así que
`CREATE TABLE x (v TIPO_QUE_NO_EXISTE)` funciona y `typeof()` responde `text`. Comprobar que un
nombre de tipo se acepta no mide nada. Cada fila sondea la afirmación que hace la razón, y todas la
confirmaron en **3.45.1, 3.46.1, 3.50.4, 3.53.2 y 3.53.4** — ninguna varía por versión.

| Capacidad | La afirmación | La evidencia |
|---|---|---|
| `UUID` | TEXT, sin tipo ni validación | acepta `'esto-no-es-un-uuid'`, `typeof` = `text` |
| `BOOLEAN` | no hay boolean: 0/1 en un INTEGER | acepta `7`, `typeof` = `integer`, devuelve `7` |
| `JSON` | TEXT: `json_*` funcionan, sin validar al escribir | acepta `'{no soy json}'` como `text`, y `json_extract` responde `1` |
| `ARRAYS` | no hay arrays: un `list[T]` va como JSON en TEXT | `ARRAY[..]` da error; una columna `INT[]` guarda `text` |
| `TIMESTAMPTZ` | no distingue tz de naive: los dos TEXT ISO-8601 | ambas columnas `typeof` = `text`, el offset dentro del texto |
| `INTERVAL` | TEXT, no comparable como duración | ordenar `['10 days','9 days']` pone `'10 days'` primero |
| `FLOAT_SPECIALS` | un NaN vuelve NULL | se guarda NaN y devuelve `None`, `typeof` = `null` |
| `DECIMAL_ORDERING` | TEXT exacto, pero ORDER BY es lexicográfico | el menor de `'9.99'`/`'10.00'` es `'10.00'` |
| `INT_WIDTHS` | no distingue anchos | `SMALLINT` acepta `100000`; mismo `typeof` que `BIGINT` |
| `ILIKE` | no hay ILIKE; `LOWER()` solo pliega ASCII | `ILIKE` da error; `LOWER('Á')` devuelve `'Á'` |

## Qué oye el usuario cuando se abre una sesión

Medido sobre SQLite con el registry global:

| Clase de aviso | Cuándo se dice | Cuántas veces |
|---|---|---|
| **de tipo** (`Decimal`, `JSON`, `UUID`, `bool`…) | solo si algún modelo declara una columna de ese tipo | una por TIPO, no por columna |
| **estructural** (`SCHEMAS`, `ROW_LOCKING`, `ILIKE`…) | siempre | una por capacidad |

Medido: seis columnas `Decimal` repartidas en dos modelos producen **un** aviso; tres columnas
`JSON` producen **uno**. Un registry con solo `int` y `str` no recibe ningún aviso de tipo. Y cada
aviso se dice **una vez por proceso** — `_warned_caveats`, en `session/shared.py`, guarda el
conjunto, así que una segunda sesión no repite nada.

Diecisiete avisos en SQLite: quince estructurales más uno por cada tipo degradado en uso. Son
diecisiete limitaciones distintas, no una repetición.

Cinco de los estructurales se podrían filtrar igual que los de tipo, porque la respuesta está en los
modelos: `SCHEMAS` (ningún modelo declara `schema=`), `STORED_FUNCTIONS` (ningún `@snake_function`),
`INDEX_METHODS` (ningún índice con `method=`), `PARTIAL_INDEXES` (ningún índice con `where=`),
`COMMENTS` (ningún `db_comment`). Los demás —`ROW_LOCKING`, `SET_ISOLATION`, `ILIKE`— dependen de
las consultas que se escriban en tiempo de ejecución, así que avisar al arrancar es la única
oportunidad que hay.

## Los estados de una capacidad

| Estado | En qué se resuelve | Lleva razón |
|---|---|---|
| `Full()` | sí, siempre | no |
| `Degraded(razón)` | funciona de otra manera | **obligatoria** |
| `Nope(razón)` | se niega en tiempo de compilación | **obligatoria** |
| `Since(versión, sentencia, below)` | `Full()` o lo que diga `below`, según `engine_version` | se compone en runtime |

`Since` es el nuevo. Lee la versión del motor y se convierte en uno de los otros, así que nadie
aguas abajo llega a ver un `Since` jamás.

`below` se escribe a mano porque solo la capacidad sabe qué SIGNIFICA su ausencia: sin el CHECK la
operación se detiene (`Nope`) y el usuario escribe un `RebuildTable`; sin un tipo nativo solo se
avisa (`Degraded`). Resolver siempre al mismo estado convertiría lo primero en lo segundo y dejaría
al plan emitir una sentencia que el motor rechaza.

La razón resultante nombra las dos versiones:

> no acepta `ALTER TABLE ... ADD CONSTRAINT`: un CHECK solo viaja dentro del `CREATE TABLE` …
> (este motor es 3.46.1; `ALTER TABLE … ADD CONSTRAINT … CHECK` existe desde 3.53.0)

De dónde sale la versión: SQLite lee `sqlite3.sqlite_version_info`, una constante del módulo, sin
conexión. Postgres y MySQL preguntan al servidor, que es de donde la leen también Django y
SQLAlchemy.

## Qué deben hacer los tests

Un test nunca se salta porque «aquí no aplica». Lee la matriz para el motor y la versión que tenga
enchufados, y exige lo que la matriz diga:

| Lo que dice la matriz | Lo que el test exige |
|---|---|
| `Full` | la sentencia nativa se ejecuta y funciona |
| `Degraded(razón)` | funciona por el sustituto, **y avisa con esa razón** |
| `Nope(razón)` | se niega, con esa razón y no con un error críptico del motor |
| `Since(v)` | el que corresponda a la versión que tiene delante |

Y otra más, en el sentido contrario: el test también le pregunta al **motor crudo**. Si la matriz
dice `Nope` y el motor acepta la sentencia, la matriz miente y el test cae. Es la única razón por la
que alguien se enteró de lo de SQLite 3.53.

## Cómo sondear sin engañarse

Escribiendo esta página se produjeron cinco resultados falsos, todos por sondas perezosas. **Una
sonda floja no falla: acusa a la matriz de mentir.**

| Trampa | Qué parecía | Qué era en realidad |
|---|---|---|
| «no lanzó» | `CAST('NaN' AS DOUBLE)` no lanza → parece soportado | devuelve **`0.0`**; guardar un NaN da `1365` |
| una sonda que no es el caso | el CTE recursivo como PRIMERA rama funciona → el `Nope` parece falso | como SEGUNDA rama —lo que dice la razón— responde `1064` |
| una sonda invertida | `INSERT 100000` en un `SMALLINT` falla → contado como «no comprueba el rango» | fallar ES la capacidad |
| una sonda más ancha que la afirmación | `CREATE OR REPLACE FUNCTION` falla en MySQL → «no tiene funciones» | `CREATE FUNCTION` funciona; lo que falta es el `OR REPLACE` |
| **SQLite acepta cualquier nombre de tipo** | `CAST('{}' AS JSONB)` funciona → parece que tiene JSONB | `CREATE TABLE x (v TIPO_QUE_NO_EXISTE)` **también funciona**, y `typeof()` responde `text` |

La última es la peor y es propia de SQLite: declarar un tipo NUNCA falla ahí, así que una sonda que
solo comprueba que el tipo se acepta no mide nada. Hay que sondear el COMPORTAMIENTO: qué responde
`typeof()`, cómo ordenan los valores, si se rechaza la basura.

Reglas que salen de ahí:

1. Comprobar el **valor** que vuelve, no que nada reventara.
2. Sondear el caso que la razón **describe**, no uno que se le parezca.
3. Cuando una capacidad se demuestra con un **rechazo**, el rechazo es el aprobado.
4. Nunca `pytest.raises(Exception)`: cualquier excepción lo aprueba, y así es como `emit_drop_check`
   siguió en verde mientras la sentencia funcionaba desde 3.53 — borraba una restricción que nunca
   había creado, recibía `no such constraint` y lo tomaba por el error de sintaxis que esperaba.

## Reglas

1. Una capacidad = una sentencia que un motor puede ganar o perder por su cuenta.
2. La razón es obligatoria y la lee el usuario, así que nombra el sustituto, no solo la carencia.
3. Nada se declara sin haberlo medido contra un motor real.
4. La matriz es la fuente de verdad. Esta página es su retrato, y un test los mantiene iguales.
