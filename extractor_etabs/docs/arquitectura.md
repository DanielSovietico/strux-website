# Notas de arquitectura

Para quien vaya a extender la aplicación.

## Capas

```
                 ┌────────────────────────────┐
   ETABS ◄──────►│ core/etabs_api.py          │  llamadas OAPI normalizadas
                 ├────────────────────────────┤
  .e2k  ────────►│ core/e2k_parser.py         │
 tablas ────────►│ core/table_import.py       │  ── todas producen ──►
                 ├────────────────────────────┤        StructuralModel
                 │ core/extractors.py         │        ResultSet
                 │ core/deflection.py         │
                 ├────────────────────────────┤
                 │ core/session.py            │  estado y flujo
                 ├──────────────┬─────────────┤
                 │ ui/ (PySide6)│ cli.py      │
                 └──────────────┴─────────────┘
```

Reglas que conviene no romper:

1. **`core` no importa Qt.** Es lo que permite probar todo sin pantalla y usar la
   lógica desde un script. La única dependencia de `core` es la biblioteca
   estándar (más `openpyxl` opcional para `.xlsx` y `comtypes`/`pythonnet`
   opcionales para la OAPI).
2. **Un solo modelo de datos.** Cualquier fuente nueva debe producir
   `StructuralModel` y `ResultSet` (`core/model.py`); nada aguas abajo debe
   preguntar de dónde vinieron los datos, salvo para etiquetar procedencia.
3. **Lo que falta se dice.** `missing` y `warnings` son parte del resultado, no
   un detalle de la interfaz. Nunca se rellena un dato ausente con un supuesto
   silencioso.

## Convención de la OAPI

Los métodos de la CSI API declaran sus salidas `ByRef` y devuelven un entero de
estado. Los dos enlaces las regresan en orden distinto:

| Enlace | Forma del retorno |
|---|---|
| comtypes | `(salida1, salida2, …, ret)` |
| pythonnet | `(ret, salida1, salida2, …)` |

`EtabsConnection.call(func, in_args, out_spec)` es el único lugar que sabe esto:
construye los marcadores de posición del tipo correcto para cada enlace, invoca,
separa `ret` y verifica que sea `0`. `try_call` hace lo mismo pero anota la falla
en `warnings` y devuelve `None`, que es lo apropiado para consultas accesorias
(un eje que no se pudo leer no debe tumbar una extracción de 200 000 renglones).

Al agregar una consulta nueva basta declarar su `out_spec` con las constantes
`INT`, `DBL`, `STR`, `BOOL` y sus versiones `…_ARR`.

## Rendimiento

- **Una llamada por grupo, no por barra.** `ResultsReader._forces_by_group` pide
  `FrameForce("All", eItemTypeElm.GroupElm)` cuando hay 25 barras o más, y filtra
  en Python. Con miles de barras la diferencia es de minutos a segundos. Si ETABS
  rechaza el grupo, se cae al método barra por barra y se anota el motivo.
- **Tabla sin copias.** `ui/table_model.py` expone las listas del `ResultSet`
  directamente a través de un `QAbstractTableModel`; no se crean *widgets* por
  celda ni se duplican los datos.
- **Hilo único de trabajo.** `ui/workers.py` mantiene un `QThread` con cola:
  COM exige que todas las llamadas salgan del hilo que creó el objeto, y la cola
  evita dos extracciones peleándose por la conexión. El *callback* de progreso
  devuelve `False` para cancelar, y `core` lo convierte en `Cancelled`.

## Agregar una cantidad nueva

Ejemplo: reacciones por nudo.

1. Un `@dataclass` de renglón en `core/model.py`.
2. Su entrada en `TABLE_SPECS` (título, columnas, campos, primera columna
   numérica). Con eso ya aparece en la interfaz, en el CSV, en el Excel y en el
   JSON: las vistas se generan desde ese diccionario.
3. Un lector en `core/etabs_api.py` (`out_spec` + desempacado) y su llamada en
   `ResultsReader.extract`.
4. Los sinónimos de columna en `core/table_import.py` (`_ALIASES` y `_classify`)
   si también se puede importar de una tabla.
5. Los filtros de su pestaña en `ui/results_view.py` (`_FILTERS`).

## Pruebas

- `tests/fake_etabs.py` simula el `SapModel` con ambas convenciones de retorno.
  Es lo que permite probar la ruta OAPI —incluido el camino alterno cuando el
  grupo falla y el reporte de «análisis sin correr»— fuera de Windows.
- `tests/test_deflection.py` contrasta el único cálculo de la aplicación contra
  soluciones cerradas.
- `tests/test_ui.py` usa `QT_QPA_PLATFORM=offscreen`; se omite si no hay PySide6.

```bash
python -m unittest discover -s tests
```
