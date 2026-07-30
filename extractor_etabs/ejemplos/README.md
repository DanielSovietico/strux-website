# Ejemplos

Archivos de muestra para probar la aplicación sin ETABS. Vienen del programa
original (`legacy/Vigas_ETABS_autocontenido.html`), que los trae como demostración.

| Archivo | Qué es |
|---|---|
| `modelo_ejemplo.e2k` | marco de concreto de 4 niveles: 5 pisos, 7 ejes, 68 trabes, 48 columnas, 3 secciones y 7 combinaciones |
| `element_forces_beams.csv` | tabla *Element Forces - Beams* exportada del mismo modelo: 4 284 renglones, 7 combinaciones |

Prueba rápida:

```bash
python -m extractor_etabs offline \
    --e2k ejemplos/modelo_ejemplo.e2k \
    --tabla ejemplos/element_forces_beams.csv \
    --deflexiones --xlsx /tmp/prueba.xlsx
```

O en la ventana: *Cargar geometría de .e2k…* y luego *Importar tabla exportada…*.
