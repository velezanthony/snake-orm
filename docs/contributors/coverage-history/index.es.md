# Histórico de cobertura

Cada corrida de `make coverage-snapshot` deja un snapshot JSON en `assets/data/`, destilado del
informe que coverage.py ya produce. Esos ficheros son el almacén; ninguna otra cosa de aquí guarda
un número.

**[Abrir el visor →](coverage/index.html)**

Necesita el repositorio servido, porque la página pide sus snapshots por fetch y un navegador se
niega a eso sobre `file://` — cada URL de ese tipo es su propio origen:

```bash
make coverage-snapshot   # measure, and record it
make coverage-serve      # then open the address it prints
```

## Qué enseña

Tres páginas sobre las mismas dos fechas. Elige la misma medición a los dos lados y ves un momento;
elige distintas y cada tabla gana su comparación.

| página | la pregunta que contesta |
|---|---|
| Trend and domains | cómo se movió el conjunto, y qué subpaquete lo movió |
| Files | dónde están de verdad las líneas sin alcanzar |
| Never entered | qué funciones no llamó ningún test |

Esa última es la razón de que esto exista. **Un porcentaje dice que una línea SE EJECUTÓ, jamás que
se COMPROBARA algo** — y un dominio que va holgado puede esconder cuerpos enteros donde ningún test
entró nunca, porque una media los tapa. Léelo junto a la escala de estrellas de
`docs/features.es.md`, donde cobertura alta al lado de una estrella es la combinación
peligrosa, no la tranquilizadora. Esa página no se publica —es el índice del proyecto, no
documentación de usuario—, y por eso aquí se nombra en vez de enlazarse.

`partial` es la otra columna que merece vigilancia: ramas tomadas de un solo lado, el `if` que corrió
mientras el `else` no lo hizo nunca. Se mueve cuando un test se afila en vez de ensancharse, que es
la mitad difícil.

## Aquí no hay números

A propósito. Una cifra escrita en un documento se desfasa el mismo día y luego miente con la
autoridad de algo escrito; el visor lee los snapshots en vivo y no puede. Borra un snapshot y sale
del histórico — no hay una segunda copia en ningún sitio que pueda contradecirlo.
