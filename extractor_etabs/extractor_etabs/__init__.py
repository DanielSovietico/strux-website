"""Extractor ETABS — extracción de momentos, cortantes y deformaciones.

Paquete organizado en dos capas independientes:

* ``extractor_etabs.core``  — lógica sin interfaz: conexión OAPI, lectores de
  archivo (.e2k y tablas exportadas), extractores de resultados y exportadores.
  No importa Qt, de modo que se puede usar desde scripts o desde la CLI.
* ``extractor_etabs.ui``    — interfaz de escritorio (PySide6) construida sobre
  la capa ``core``.

Regla heredada del programa original: no se inventan datos. Lo que el modelo o
la tabla no contengan se reporta como faltante y la interfaz lo muestra así.
"""

from .version import __version__, APP_NAME, APP_ID

__all__ = ["__version__", "APP_NAME", "APP_ID"]
