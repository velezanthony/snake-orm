# Límites conocidos

**Parte del contrato**, no una lista de disculpas.

## Del mecanismo de tipos

- **`type[Brand]` es llamable.** El checker acepta `Car.brand()`. No hace nada útil y no hay forma
  de prohibirlo con descriptores recursivos.
- **`==` sobre una expresión de clase devuelve `SnakeCondition`, no `bool`.** Consecuencia: `assert
  Car.price == 100` **siempre pasa** (es *truthy*).
- **La tupla `field_specifiers` está duplicada cinco veces.** Lo impone PEP 681. Un test la mantiene
  sincronizada; eliminarla no se puede.

## De las consultas

- **El streaming no convive con un `include()` de a-muchos.** `session.iterate()` SÍ existe (síncrono
  y asíncrono) y recorre el resultado sin materializarlo — cursor del servidor en Postgres y MySQL,
  `fetchmany` en SQLite. Con lo que **lanza** es con un `include()` de a-muchos o un prefetch: el
  select-in necesita TODAS las raíces para su segunda consulta, y en streaming no existen. El
  `include()` de a-uno sí vale (viaja en el mismo JOIN). Todo lo demás —`all()`, `first()`— sí
  materializa el resultado entero en memoria.
- **`only()`/`defer()` no se combinan con `include()`.** El emisor con includes construye su
  lista de columnas por segmentos; meterle un subconjunto es otra pieza. Se RECHAZA, no se
  ensancha en silencio, y el mensaje lo dice.
- **`session.select()` proyecta CUATRO columnas como mucho.** Las sobrecargas se paran en `c4`, así
  que una quinta no es una tupla más laxa: es `No overload variant of "select" matches`, en tiempo
  de compilación. Parte la proyección en dos selects, que además es la forma que se sigue leyendo.
  Ensancharlo es una línea por aridad en un fichero que ya lleva cuatro.
- **`annotate` valida en runtime** que la query sea del mismo modelo que el `@snake_result`, no en el
  checker.
- **Los CHECK no admiten subconsultas** (`EXISTS`, `IN (SELECT ...)`). Se rechaza al declararlos —
  PostgreSQL tampoco los admite ahí.
- **`in_()` no trocea por el tope de marcadores.** `add_all()` y el select-in de `include()` sí;
  `in_()` emite un marcador por valor, contra 65.535 en Postgres y MySQL y 32.766 en SQLite. Revienta
  en el driver al ejecutar, no al construir. Trocea a mano un `in_()` grande.
- **Un `IN` compuesto tiene DOS techos, y el ORM solo guarda el que puede saber exacto.** Los
  parámetros son `anchura × nº de claves`, y pasarse del límite declarado del motor se rechaza antes
  de emitir, nombrando las dos cifras. PostgreSQL se para ANTES y por otro motivo: medido sobre 17,
  rechaza alrededor de ocho mil CLAVES con `stack depth limit exceeded` a cualquier anchura, que es
  la recursión del parser y no los 65.535 del protocolo. Esa cifra se mueve con el `max_stack_depth`
  del servidor, así que el ORM no se adelanta: rechazar en un número copiado de la configuración de
  un servidor prohibiría en uno afinado lo que allí la base de datos permite. Trocea la lista de
  claves a mano y combina los resultados.
- **Las escrituras masivas no disparan señales.** `update_where`/`delete_where` son una sentencia SQL;
  no hay instancias que notificar. El ORM avisa si el modelo tiene señales registradas.
- **`DISTINCT ON` está fuera de alcance.** `distinct()` emite el `DISTINCT` estándar sobre el SELECT
  entero, nunca el `DISTINCT ON (...)` de Postgres. Es una extensión de un solo motor, así que si
  algún día entra, entra por el catálogo `Cap` con un `Nope` en los otros dos —no como un método que
  funciona en un motor de tres y se calla en los demás—. Para una consulta solo de Postgres hoy,
  `session.raw`.

## De los números y el JSON

- **Un `dict` en `JSONB` se NORMALIZA.** Reordena claves, quita duplicadas y normaliza números
  (`100.0` == `100`). Es la naturaleza de `jsonb`. Para texto exacto:
  `json_storage=SnakeJsonStorage.JSON`.
- **`json_get(as_type=...)` solo admite `str`, `int`, `float` o `bool`.** Un `Decimal` o un
  `datetime` lanzan `SnakeUnsupportedFeature`.
- **Una clave JSON tiene que ser un identificador simple.** Se emite DENTRO de la sentencia, no como
  parámetro, así que una clave con espacio o punto se rechaza con `SnakeValueError`.
- **Un `int` mayor que ±9,2·10¹⁸ no cabe.** El defecto es `BIGINT` (64 bits). Más allá, usa `Decimal`
  (mapea a `NUMERIC`, precisión arbitraria). La `scale` se **valida al escribir** (`SnakeValueError`).
- **Una columna `datetime` no tiene forma por defecto: la eliges tú.** `snake_datetime()` sobre
  `SnakeColumn[datetime]` es una HORA DE PARED (`TIMESTAMP`, sin zona); `snake_datetimetz()` sobre
  `SnakeColumn[SnakeUtc]` es un INSTANTE (`TIMESTAMPTZ`). Un `datetime` declarado con un
  `snake_column()` pelado se rechaza al importar, y mezclar las dos —un valor con zona en una columna
  de hora de pared, uno naive en una de instante— lanza `SnakeValueError` al escribir. El ORM nunca
  tira un `tzinfo` en silencio.
- **Una columna `TIMESTAMPTZ` solo admite UTC.** Guarda el instante, no el offset: `14:30+02:00`
  volvería de Postgres como `12:30+00:00` y de SQLite como `14:30+02:00`, así que `.hour` dependería
  del motor. Conviértelo tú con `to_utc(value)`.

## De SQLite

- **No hay esquemas con nombre.** Los "esquemas" son bases adjuntas (`ATTACH`); el `schema=` se
  ignora al emitir.
- **No hay `ALTER TABLE ADD CONSTRAINT`, y hay dos desenlaces, no uno.** Los CHECK y las FK van dentro
  del `CREATE TABLE`, así que cambiar uno en una tabla que ya existe pasa por rehacerla. Una migración
  autodetectada LO HACE: el diff colapsa el cambio en un único `RebuildTable`, y SQLite lo deletrea
  entero (`PRAGMA defer_foreign_keys = ON`, crear la forma nueva al lado, copiar las filas, tirar la
  tabla vieja, renombrar). Lo que sí **para y lo dice** es un plan escrito a mano: un `AddCheck` o un
  `AddForeignKey` le pregunta a `Cap.ADD_CONSTRAINT`, que aquí es `Nope`, y el plan lo rechaza
  nombrando la salida. `UNIQUE` sí se traduce (a índice único).
- **Reconstruir es la única forma de tirar una columna que sujeta una clave ajena.** SQLite
  contesta `unknown column ... in foreign key definition`, así que `Cap.DROP_COLUMN_CASCADES_FK` es
  `Nope` y el plan para el `DropColumn` nombrando la clave. A diferencia de MySQL, poner un
  `DropForeignKey` delante NO lo desbloquea: este motor tampoco tiene `DROP CONSTRAINT`, así que esa
  operación para en `Cap.ADD_CONSTRAINT` — medido, una migración autodetectada que quita una relación
  y su columna se niega en las dos operaciones. La tabla hay que reconstruirla a mano, con un `RunSQL`.
- **No hay `ALTER COLUMN`.** Cambiar tipo o nulabilidad de una columna existente no existe aquí.
- **No hay `CREATE OR REPLACE VIEW` ni funciones almacenadas.** Lo primero se reescribe como `DROP` +
  `CREATE`; lo segundo se para en el plan.
- **Los `COMMENT ON` se omiten al crear, y se rechazan al alterar.** Un `CREATE TABLE` que lleve
  `db_comment` emite la tabla y deja fuera los comentarios; un `AlterTableComment` —una operación
  cuyo único cometido es cambiar uno— para en el plan con `Cap.COMMENTS`. No hay nada que cambiar en
  un motor que no guarda ninguno.
- **No hay `SELECT ... FOR UPDATE`.**
- **No guarda tamaños ni precisión.** Su sistema es de **afinidades**: `SMALLINT/INTEGER/BIGINT` son
  el mismo `INTEGER`; `VARCHAR(50)/TEXT/CHAR(10)` el mismo `TEXT`. `int_size`, `max_length` y
  `precision`/`scale` los honra Postgres; aquí se aceptan por portabilidad pero no se imponen.
- **Un `Decimal` se ordena como TEXTO.** Se guarda como `TEXT` para no perder exactitud, así que
  `ORDER BY` es lexicográfico (`'100.00'` antes que `'99.00'`). Para orden numérico:
  `ORDER BY CAST(price AS REAL)` a mano.
- **Tampoco hay arrays.** Igual que en MySQL: una `list[T]` se guarda como JSON en una columna `TEXT`
  y vuelve siendo la misma lista, pero no se puede consultar dentro de ella desde SQL.
- **Un `float` NaN vuelve como `NULL`.** SQLite no sabe guardarlo (`Inf`/`-Inf` sí). Postgres sí.
- **No hay timeout de sentencia en el servidor.** `TimeoutDriver` se niega a envolver un driver de
  SQLite (`SnakeDialectError`): `busy_timeout` espera un cerrojo, no hace nada con una consulta
  lenta.

## De MySQL / MariaDB

- **Tampoco hay funciones almacenadas.** `Cap.STORED_FUNCTIONS` es `Nope` aquí igual que en SQLite, y
  por un motivo distinto: el cuerpo de una rutina es SQL crudo y reemplazarla depende de
  `CREATE OR REPLACE FUNCTION`, que MariaDB acepta y MySQL rechaza de plano. Un solo dialecto sirve a
  los dos, así que no puede prometer lo que solo uno cumple. `@snake_function` es **solo PostgreSQL**.

- **No hay `RETURNING`.** `add()` recupera el PK autoincremental (`lastrowid`); `add_all()` de un lote
  NO rellena los PKs. No es en silencio: el ORM lanza un `SnakeWarning` una vez por motor, y las filas
  SÍ se insertan — lo que queda sin valor es el `id` en memoria. Si ese id iba a ser la clave foránea
  de la fila siguiente, la guarda de valor obligatorio lanza un `SnakeValueError` que nombra la
  columna. Si necesitas los ids, inserta con `add()` uno a uno, o ramifica con
  `session.dialect.supports_returning`.
- **No hay instantes nativos: `snake_datetimetz()` cae a TEXT.** El único tipo con zona de MySQL
  (`TIMESTAMP`) topa en el año 2038 y `DATETIME` no es tz-aware, así que un `SnakeUtc` se guarda como
  texto ISO-8601. El instante vuelve **entero**, huso incluido; lo que se pierde es que el motor lo
  trate como una fecha al ordenar, comparar y operar. Va declarado `Degraded`, así que la sesión
  avisa una vez. Un `snake_datetime()` (hora de pared) SÍ es un `DATETIME` nativo, y su precisión
  declarada se honra (`snake_datetime(precision=3)` → `DATETIME(3)`), con un tope de 6 dígitos.
- **Un `Decimal` tiene que declarar su precisión.** Aquí no hay decimal sin límite: un `DECIMAL`
  pelado es `DECIMAL(10,0)`, así que `9.99` se guarda como `10` —medido—. Se rechaza al emitir en vez
  de degradarse porque el `NUMERIC` de Postgres es de precisión arbitraria y el mismo modelo no
  pierde nada allí. Declara `snake_decimal(precision=..., scale=...)` y es portable en los tres.
- **Un `DECIMAL` para en 65 dígitos y 30 decimales.** Postgres llega a 1000, así que un
  `snake_decimal(precision=500, scale=2)` es válido allí e imposible aquí: se rechaza al emitir el
  DDL, nombrando el motor. Son dos topes distintos — `DECIMAL(40,35)` tiene la precisión dentro del
  límite y la escala fuera.
- **No hay tipo para `timedelta` ni arrays.** No se rechaza ninguno de los dos: un `timedelta` se
  guarda como `TEXT` y una `list[T]` como JSON en una columna `TEXT`, y los dos vuelven siendo lo que
  eran. `Cap.INTERVAL` y `Cap.ARRAYS` son `Degraded`, no `Nope` — lo que se pierde es que el motor
  sume una duración a una fecha o consulte DENTRO del array. `bool` es `TINYINT(1)` y `UUID` es
  `CHAR(36)` (round-trippean, no son nativos).
- **No hay índices parciales, y el mismo `Nope` tiene DOS destinos.** El `WHERE` no forma parte del
  `CREATE INDEX` de MySQL, así que `Cap.PARTIAL_INDEXES` es `Nope` — y lo que pasa después depende del
  índice. Un índice de BÚSQUEDA declarado con `where=` se **degrada**: se le quita el `WHERE` y se crea
  sobre la tabla entera. Encuentra las mismas filas y cuesta más espacio, y la sesión lo dice una vez.
  Un índice **UNIQUE** parcial **para el plan**: ensanchar `UNIQUE(email) WHERE deleted_at IS NULL` a
  `UNIQUE(email)` prohíbe filas que el dominio permite, que es otro esquema y no uno más lento. O
  quitas el `unique=True`, o expresas la regla con una columna generada más un `UNIQUE` normal encima
  en un `RunSQL`.
- **Tirar la clave antes es lo que libera una columna que sujeta una clave ajena.** InnoDB necesita el índice sobre el
  que se apoya la clave y contesta el error `1553`, así que `Cap.DROP_COLUMN_CASCADES_FK` es `Nope` y
  el plan para el `DropColumn` nombrando la clave. La salida está una operación antes: un
  `DropForeignKey` delante del `DropColumn`, que es justo lo que ya emite la migración autodetectada —
  una escrita a mano tiene que decirlo, y decirlo es además lo que permite al rollback devolver la
  clave.
- **El DDL no es transaccional.** Cada `ALTER`/`CREATE` hace commit implícito: si el paso 3 falla, 1 y
  2 quedan aplicados. El runner lo avisa. Migra en pasos pequeños y reversibles.
- **Un "schema" ES una base de datos.** No hay esquemas con nombre dentro de una, así que
  `@snake_model(schema=...)` no aplica aquí.
- **Un comentario es una cláusula, y cambiar el de una COLUMNA reescribe la columna.** MySQL no
  tiene `COMMENT ON` —es un error de sintaxis—, pero sí guarda comentarios: el de la tabla va dentro
  del `CREATE TABLE` (`... COMMENT = '...'`) y se cambia con `ALTER TABLE ... COMMENT = '...'`, y el
  de una columna vive en la definición de esa columna. Esa primera mitad es una GRAFÍA, y el
  dialecto la traduce, así que un `db_comment` ya no se descarta aquí. La segunda mitad es la razón
  de que `Cap.COMMENTS` sea `Degraded` y no `Full`: no existe sentencia que cambie el comentario de
  UNA columna, así que el ORM emite un `MODIFY COLUMN` con la definición entera reescrita a partir
  de tu modelo. Todo lo que el modelo declara sobrevive; lo que la base guarda y el modelo no
  describe —una collation, un `ON UPDATE CURRENT_TIMESTAMP`, una expresión generada— no. Ojo además
  a que en este motor un comentario vacío y ningún comentario son el mismo valor.
- **`TimeoutDriver` emite `SET SESSION max_statement_time`**, que es la variable de MariaDB. El MySQL
  de Oracle la rechaza con `1193 Unknown system variable` al envolver el driver.

## De la introspección

- **El round-trip no es biyectivo.** `TEXT`, `VARCHAR(50)` y `CHAR(10)` vuelven todos como `str`. Es
  correcto, no un fallo.
- **Lo que el ORM no sabe expresar se avisa, no se representa.** Triggers, tipos exóticos e índices
  por expresión salen como comentario y aviso por consola.

## De las migraciones

- **Los renombrados no se detectan solos.** El diff ve un `DROP` y un `ADD`; **sugiere** un
  `RenameColumn` por consola, pero no decide. Adivinar pierde datos.
- **Un squash para cuando cruza una migración de datos.** `RunPython`/`RunSQL` mutan filas, así que
  colapsarlas exigiría EJECUTARLAS, y un squash no toca la base de datos. Colapsa el tramo que llega
  hasta ella y deja el resto del histórico como está.
- **Un squash no borra las migraciones que reemplaza, y es a propósito.** Puede haber una base con
  solo algunas de ellas aplicadas, y los ficheros originales son los que le permiten ponerse al día.
  Borrarlos es una decisión de una persona, más adelante.
- **Alternar `int` ↔ autoincremental SÍ se emite, y en Postgres es la secuencia escrita entera.**
  `BIGSERIAL` no es un tipo: es un atajo de `CREATE TABLE`, y un `ALTER ... TYPE BIGSERIAL` recibe
  del servidor `type "bigserial" does not exist`. Así que la migración emite lo que el atajo
  SIGNIFICA —`CREATE SEQUENCE`, `SET DEFAULT nextval(...)`, `ALTER SEQUENCE ... OWNED BY` y un
  `setval` al `MAX` actual para que no se repita ninguna clave— y el inverso quita el default y la
  secuencia. MySQL lo lleva dentro del `MODIFY COLUMN`, y exige que la columna sea clave
  (`1075 there can be only one auto column and it must be defined as a key`). SQLite para en el
  plan, con `Cap.ALTER_COLUMN`.
- **`RebuildTable` solo colapsa un cambio de constraints PURO, y en SQLite no siempre basta.** Cuando
  lo único que ha cambiado de una tabla son sus CHECK y sus claves ajenas, el diff emite un único
  `RebuildTable` en vez de `AddCheck`/`AddForeignKey` sueltos, y cada motor lo deletrea a su manera —
  Postgres y MySQL con el `ALTER` mínimo, SQLite con la reconstrucción entera. De ahí salen dos
  límites. Primero, el colapso exige que los constraints sean la ÚNICA diferencia: añade una columna
  en el mismo paso y la tabla se va por el camino normal, porque un par de snapshots que discrepara
  en una columna se aplicaría en SQLite (que recrea desde `after`) y no en Postgres (cuyo `ALTER`
  mínimo no emite nada para eso) — `RebuildTable` se niega a construirse así y nombra lo que
  discrepa. Segundo, la reconstrucción lleva `PRAGMA defer_foreign_keys = ON`, que mueve el veredicto
  al `COMMIT`; eso basta para una tabla a la que no apunta nadie, y NO basta cuando la clave de otra
  tabla nombra a la que se está rehaciendo — el `DROP TABLE` sube el contador diferido, nada lo baja,
  y el `COMMIT` se niega. Un fallo ruidoso y atómico, no un esquema corrupto.
- **`RunPython` sin `backward` no se puede deshacer.** El rollback lanza un error que dice qué añadir.
- **El runner asíncrono no ejecuta migraciones de datos.** `RunPython` recibe una sesión síncrona.

## De la herencia polimórfica

- **Las columnas propias de una hija tienen que admitir `NULL`.** La tabla es una sola y existen
  también en las filas hermanas. Se comprueba al declarar.
- **Un discriminador desconocido se hidrata como la clase base.** Se pierden los campos de la
  subclase; no la fila.
- **No hay herencia joined-table, y está DESCARTADA, no aplazada.** Una tabla por subclase unidas por
  la clave primaria —Django la llama herencia multi-tabla; SQLAlchemy, `joined table inheritance`—
  no existe ni está prevista. La tabla única con discriminador ya cubre el polimorfismo que el
  dominio pide, y su precio es la regla del `NULL` de arriba: las columnas propias de una hija
  existen también en las filas de sus hermanas. La joined-table recuperaría esas columnas y cobraría
  a cambio un JOIN por lectura, y sería una SEGUNDA estrategia de herencia atravesando el
  compilador, el linker, el emisor y el hidratador. Si algún día un dominio se le queda grande a la
  tabla única, el argumento llegará con él.

## De la declaración y las sesiones

- **Un destino de relación solo importable bajo `TYPE_CHECKING` rompe `snake_link()`.** El linker usa
  `get_type_hints` (evalúa en runtime): sale un `NameError` crudo. Declara los modelos a nivel de
  módulo, importables en runtime.
- **El `__exit__` de la sesión no cierra el driver (por diseño).** Hace commit/rollback al salir; el
  driver es inyectado. Para devolverlo al pool, `session.close()` (sync y async).
- **En Postgres, `TimeoutDriver` fija `statement_timeout` con `SET`, no `SET LOCAL`.** Un `rollback`
  lo revierte. Para un timeout robusto, ponlo en el DSN
  (`options='-c statement_timeout=...'`).
- **El nombre de rutina de `call()` / `execute_procedure()` se VALIDA, no se cita.** Los argumentos
  viajan parametrizados; el nombre no puede — ningún motor acepta un marcador donde va un
  identificador —, así que llega al SQL tal cual y cada parte separada por puntos tiene que ser un
  identificador simple (una letra o `_`, y luego letras, dígitos, `_` o `$`). Cualquier otra cosa es
  un `SnakeValueError` antes de que exista SQL. No se cita a propósito: un `CREATE FUNCTION
  CalculatePayroll` sin comillas queda en el catálogo de PostgreSQL como `calculatepayroll`, así que
  citar la llamada dejaría de encontrarlo. Para un nombre que de verdad necesite comillas, escribe la
  sentencia con `raw(...)`.

## Una clave primaria de texto necesita longitud en MySQL

`snake_str(primary_key=True)` sin `max_length` se convierte en `TEXT`, y MySQL y MariaDB no admiten
una columna `TEXT` en una clave — una clave necesita longitud y `TEXT` no la tiene. El ORM se niega
a emitir ese `CREATE TABLE` y dice qué columna y qué argumento:

```python
key: SnakeColumn[str] = snake_str(primary_key=True, max_length=32)
```

**No elige una longitud por ti**, y eso es lo importante, no un olvido. Un `VARCHAR(255)` por
defecto haría que la tabla se creara y metería en el esquema un límite que nadie decidió; el día que
un valor lo superase, el dato se truncaría en vez de rechazarse.

Solo se rechaza la CLAVE PRIMARIA. Un `UNIQUE` o un índice sobre una cadena sin longitud lo acepta
MariaDB y se deja en paz, porque prohibir lo que el motor permite es otra forma de estar mal.

## Lo que directamente no hay

- **Identity map.** Dos consultas a la misma fila dan dos objetos. `a == b` es `True` (por PK), pero
  `a is b` es `False`.
- **Lazy loading.** A propósito: acceder a una relación no cargada lanza. Es lo que hace el N+1
  imposible por defecto.
- **Búsqueda full-text.** Con `session.raw`, pero sin API tipada.
- **Operadores JSON de contención y ruta.** `json_get()` lee una clave con cast declarado; `@>`, `?`
  y compañía no tienen API tipada. Los tres motores usan tres mecanismos distintos para ellos.
- **Operadores de array.** Una columna `list[T]` va y vuelve en los tres —nativa en PostgreSQL, texto
  JSON en los otros—, pero consultar DENTRO no tiene API. Eso es lo que `Cap.ARRAYS` llama degradado.
- **`notices` y `statusmessage` del servidor.** El Protocol del driver no expone el cursor, que es lo
  que permite que un dialecto sirva a todos; el precio es que el aviso de un trigger es invisible.
- **Una página de error propia del ORM.** Cuando revienta dentro de un framework, la página que sale
  es la del framework, y no sabe nada del ORM.
- **Motores más allá de PostgreSQL, MySQL/MariaDB y SQLite.** Esos tres son de primera clase, síncrono
  y asíncrono. Para un cuarto —SQL Server, Oracle— la costura está lista y los ficheros no están
  escritos.
```python
# No typed API for any of the four. The way through is `raw()`, which still hydrates:
from snakeorm import SnakeRow, snake_row

@snake_row
class Hit(SnakeRow):
    id: int
    title: str

hits = session.raw(
    "SELECT id, title FROM posts WHERE to_tsvector(title) @@ to_tsquery(%s)",
    ["orm"],
    into=Hit,
)
```


---

Volver a [cómo funciona el tipado](typing.es.md) o a la [arquitectura](../../contributors/architecture.es.md).
