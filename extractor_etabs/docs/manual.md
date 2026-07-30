# Manual de uso

## 1. Conectarse a ETABS

1. Abre ETABS con tu modelo y **corre el análisis** (`F5`). ETABS solo entrega
   resultados cuando el modelo queda bloqueado; si no lo está, la aplicación te
   lo dice y, con la casilla *Correr el análisis en ETABS si hace falta*, lo pide
   ella misma.
2. En las combinaciones que te interesan, verifica que estén disponibles para
   salida (*Display ▸ Load Cases/Combinations*). La aplicación las selecciona por
   ti antes de leer, pero una combinación que no existe en el modelo se reporta
   como rechazada.
3. En el Extractor: **Conectar con ETABS abierto** → **Leer geometría del
   modelo** → marca casos y cantidades → **Extraer de ETABS**.

Si no hay ninguna instancia abierta, «Abrir modelo en ETABS…» lanza ETABS,
abre el archivo y lee la geometría en un solo paso. Extensiones válidas:
`.EDB`, `.E2K`, `.$ET`, `.xlsx`, `.xls`, `.mdb`, `.accdb`.

### Cuando la conexión falla

| Síntoma | Causa habitual | Qué hacer |
|---|---|---|
| «No se encontró una instancia de ETABS abierta» | ETABS no está corriendo, o corre como administrador y Python no (o al revés) | abre los dos con el mismo nivel de privilegio, o usa «Abrir modelo en ETABS…» |
| «No se pudo cargar la API de ETABS» | falta `comtypes`/`pythonnet`, o Python es de 32 bits y ETABS de 64 | `pip install comtypes`; usa Python de 64 bits |
| «No se encontró ETABSv1.dll» (ruta pythonnet) | instalación en carpeta no estándar | define la variable de entorno `ETABS_DLL` con la ruta completa |
| «ETABS devolvió el código 1 en …» | el modelo no tiene ese objeto, o la versión no expone ese método | revisa el **Registro**: la aplicación anota la consulta exacta y sigue con el resto |
| ETABS se queda pensando | la OAPI trabaja en el hilo de ETABS | espera; la ventana sigue viva y el botón **Cancelar** corta en el próximo aviso de avance |

Ejecuta `python -m extractor_etabs diagnostico` y pega su salida cuando reportes
un problema.

## 2. Trabajar sin ETABS

### Geometría: archivo `.e2k`

En ETABS: **File ▸ Export ▸ ETABS .e2k Text File**. El `.e2k` trae niveles,
ejes, nudos, secciones y la asignación de barras por nivel — todo lo necesario
para ubicar cada resultado y para calcular deflexiones. **No trae resultados de
análisis**, y la aplicación lo reporta como faltante.

### Resultados: tablas exportadas

En ETABS: **File ▸ Export ▸ Tables to Excel** (o *to CSV*), y elige:

| Tabla | Da |
|---|---|
| **Element Forces - Beams** | `M3`, `V2`, `P`, `T`, `M2`, `V3` por estación |
| **Element Forces - Columns** | lo mismo para columnas |
| **Joint Displacements** | `U1`/`U2`/`U3` y `R1`/`R2`/`R3` (o `Ux`…`Rz`) |
| **Story Drifts** | derivas de entrepiso |
| **Base Reactions** | reacciones globales |

Las tablas se reconocen por sus **columnas**, no por su nombre, así que sirven
igual reordenadas o con encabezados en español. Un archivo puede traer varias
tablas concatenadas: cada bloque `TABLE: "…"` se lee por separado. El renglón de
unidades que ETABS pone debajo del encabezado se usa para saber en qué unidades
vienen los datos.

Al importar una segunda tabla, la aplicación pregunta si **agregar** a lo ya
cargado (por ejemplo, fuerzas y desplazamientos) o **reemplazarlo**.

## 3. Filtrar y exportar

- Cada tabla de resultados filtra por **nivel**, **elemento** y **caso**, además
  de la búsqueda libre que mira todas las columnas.
- Los decimales se ajustan por tabla, sin volver a extraer.
- `Ctrl+C` copia la selección (o todo lo visible, si no hay selección) con
  encabezados, listo para pegar en Excel.
- **Archivo ▸ Exportar todo a Excel** deja un libro con una hoja por cantidad más
  la hoja *Procedencia*, que registra fuente, unidades, casos, faltantes y
  avisos. Es lo que hace trazable el archivo meses después.

## 4. Diagramas

Elige nivel, barra y caso. Se trazan `M3`, `V2` y la deflexión calculada, con el
máximo y el mínimo rotulados y la envolvente de la barra sobre todos los casos
extraídos en la franja superior.

La casilla *M positivo hacia abajo* cambia la convención de dibujo: marcada, el
momento positivo se traza del lado de la tensión, como en los diagramas hechos a
mano; sin marcar, hacia arriba.

**Guardar PNG…** exporta el dibujo al doble de resolución para pegarlo en una
memoria de cálculo.

## 5. Volver al visor de vigas

El visor original (`legacy/Vigas_ETABS_autocontenido.html`) lee dos cargas
útiles, `etabs_model` y `etabs_frame_forces`. **Archivo ▸ Exportar JSON para el
visor de vigas** genera exactamente ese formato a partir de lo extraído, de modo
que el diseño de vigas siga funcionando con datos frescos del modelo.

Desde la CLI: `--puente puente_strux.json`.

## Empaquetado

```bash
pip install pyinstaller
python empaquetar.py                 # carpeta (arranque rápido)
python empaquetar.py --un-archivo    # un solo .exe (más lento al abrir)
```

`empaquetar.py` incluye la carpeta `ejemplos/` y el visor de `legacy/` dentro del
paquete, y no agrupa `comtypes` a la fuerza: se toma del entorno de la máquina
donde se compile. Compila **en Windows** para obtener un `.exe`.

## Unidades

El sistema se elige en el panel (y con `--unidades`). La aplicación lo fija en
ETABS antes de leer, de modo que los números y la etiqueta siempre correspondan.
Las dimensiones de las secciones se guardan siempre en centímetros, y las
longitudes y estaciones en la longitud del sistema elegido.

| Clave | Fuerza · longitud |
|---|---|
| `Ton_m_C` | tonf · m (MKS, por omisión) |
| `kgf_cm_C` | kgf · cm |
| `kgf_m_C` | kgf · m |
| `kN_m_C` | kN · m (SI) |
| `kN_mm_C` | kN · mm |
| `N_mm_C` | N · mm |
| `kip_ft_F` | kip · ft |
| `kip_in_F` | kip · in |
