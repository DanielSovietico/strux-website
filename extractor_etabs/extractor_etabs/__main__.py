"""Punto de entrada: ``python -m extractor_etabs``.

Sin argumentos abre la ventana; con argumentos usa la línea de comandos.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
