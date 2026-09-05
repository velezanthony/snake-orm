# Política de seguridad

## Reportar una vulnerabilidad

Si encuentras un fallo de seguridad en SnakeORM, **no abras un issue público**. Usa el reporte
privado de vulnerabilidades de GitHub ("Report a vulnerability" en la pestaña *Security* del repo),
que abre un canal privado con los mantenedores.

Incluye, si puedes: una descripción, los pasos para reproducirlo, la versión afectada y el impacto
que crees que tiene. Intentamos responder en un plazo razonable y te mantendremos al tanto del
arreglo y la divulgación.

## Diseño orientado a la seguridad

Algunas decisiones del proyecto son directamente defensivas:

- **SQL siempre parametrizado.** La emisión devuelve `(sql, params)` y los valores NUNCA se
  interpolan en el string; van como parámetros del driver. Esto cierra la puerta a la inyección SQL
  por construcción, no por diligencia.
- **Escape en la herramienta de debug.** El panel de debug (`snakeorm.debug`) escapa todo el SQL y
  los parámetros que renderiza: un valor malicioso no puede convertirse en XSS.

## Aviso: el debug NO se activa en producción

La herramienta de depuración puede exponer SQL, parámetros y estructura de la base de datos. Los
canales que revelan datos son **tres** —`ssr`, `envelope` y `sidecar`— y los tres se **caen en
producción** aunque estén en la configuración: el gate de entorno manda sobre la config. En Django se
ata a `settings.DEBUG`.

**`ssr` es el más ancho de los tres**, y es el que se lee como inofensivo. Los otros dos entregan el
SQL a quien lo pidió; `ssr` pinta un panel dentro de la propia página, con los valores de los
parámetros ya sustituidos en la sentencia. Un visitante anónimo se lleva la consulta y los datos con
los que se ejecutó.

El conjunto no es una lista mantenida a mano: cada canal declara su audiencia en
`snakeorm.debug.channel`, y olvidarse de clasificar uno revienta al importar. `ssr` estuvo fuera del
conjunto de riesgo una temporada — por eso esta página nombra los tres en vez de contarlos.

**Del entorno no se adivina nada.** Se declara con `SNAKE_ORM_PRODUCTION`, con `production=` en el
middleware o en `SnakeDebugConfig`. Si hay un canal de riesgo encendido y nadie ha declarado el
entorno, los middlewares WSGI y ASGI **se niegan a arrancar** en vez de elegir un defecto — asumir
«desarrollo» serviría el panel en producción, y asumir «producción» apagaría en silencio una
herramienta que alguien pidió.

Un panel de queries servido en producción es superficie de ataque en bandeja. Mantén
`SNAKE_ORM_DEBUG` apagado (o sin los canales de riesgo) fuera de desarrollo.
