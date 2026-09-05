# Para contribuidores

```bash
make sync    # uv sync --all-extras --all-groups: package, extras and every group
make audit   # the CI gate before any PR
```

El lado del desarrollo de SnakeORM.

## Qué abarca el proyecto

Fíjalo aquí, antes de que otra página lo contradiga:

- **Tres motores de primera clase**: PostgreSQL, MySQL/MariaDB y SQLite. Se implementaron en ese
  orden y cada uno es un fichero nuevo en `dialects/` y otro en `drivers/`, nunca un refactor. Un
  modelo escrito una vez corre en los tres.
- **Síncrono Y asíncrono**, sobre la misma costura incolora. Generar SQL no ejecuta nada, así que no
  tiene "color": `AsyncDriver` y `AsyncSession` entraron sin reescribir ni el compiler ni el
  dialecto. Las dos sesiones consumen el MISMO `Plan` y el mismo catálogo de mensajes.

Ésa es la superficie que cualquier cambio tiene que dejar en pie. Tocar un dialecto obliga a mirar
los otros dos; tocar la sesión, a mirar los dos colores.

## Por dónde seguir

- **[Entorno de desarrollo](development.es.md)** — uv, devcontainer, base de datos.
- **[Testing](testing.es.md)** — la suite, cómo correrla y los gates del CI.
- **[Arquitectura](architecture.es.md)** — el pipeline modelo → metadata → SQL.
- **[Interioridades](internals.es.md)** — dónde vive el código de cada funcionalidad, una a una.
- **[Las demos](frameworks.es.md)** — el único sitio donde el ORM se ejercita como lo ejercitaría
  una aplicación, con un servidor delante y una base de datos real.
- **[Proceso de release](release.es.md)** — versionado, empaquetado y publicación.

Antes de tocar código, lee el `CONTRIBUTING.md` de la raíz: reglas del proyecto (Strict TDD, cero
`Any`, commits convencionales) y flujo de Pull Request.
