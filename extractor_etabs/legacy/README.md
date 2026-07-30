# Programa original

Este es el punto de partida de la aplicación, tal como se recibió.

| Archivo | Qué es |
|---|---|
| `Vigas_ETABS_autocontenido.html` | visor y diseñador de vigas de Strux (NTC-Concreto 2023 / ACI 318-25), autocontenido: se abre con doble clic en cualquier navegador |
| `etabs_import.js` | el lector de ETABS que trae dentro, extraído del paquete para poder consultarlo |

## Qué se conservó de aquí

`etabs_import.js` ya definía el contrato de un puente de escritorio con ETABS:

```js
function oapiAvailable() {
  const b = window.struxBridge;
  return !!(b && b.etabs_model && b.etabs_frame_forces);
}
```

Ese contrato es el que cumple `extractor_etabs/core/strux_payload.py`: genera las
cargas útiles `etabs_model` y `etabs_frame_forces` con la forma exacta que
esperan `fromOapiModel` y `fromOapiFrameForce`, de modo que el visor siga
sirviendo con datos frescos del modelo sin cambiarle una línea.

Desde la aplicación: **Archivo ▸ Exportar JSON para el visor de vigas**.
Desde la terminal: `python -m extractor_etabs offline … --puente puente.json`.

## Qué se rehízo y por qué

El visor lee geometría del `.e2k` y elementos mecánicos de una tabla pegada a
mano, y su alcance es el diseño de una cadena de trabes. La aplicación de
escritorio amplía eso a lo que pedía el encargo:

- conexión real con ETABS por la OAPI (adjuntarse a la instancia abierta, abrir
  un `.EDB`, correr el análisis si hace falta);
- todas las cantidades, no solo `M3` y `V2`: `P`, `T`, `M2`, `V3`,
  desplazamientos y rotaciones de nudos, derivas y reacciones;
- todos los casos y combinaciones a la vez, con filtros y envolventes;
- columnas y diagonales además de trabes;
- exportación a Excel, CSV y JSON con la procedencia registrada.

El criterio del original se mantuvo intacto: **no se inventa nada**; lo que la
fuente no contiene se reporta como faltante.
