#!/usr/bin/env python3
"""Lanzador del Extractor ETABS.

Se puede ejecutar con doble clic o desde la terminal:

    python run.py

Funciona sin instalar el paquete: agrega su propia carpeta a ``sys.path``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extractor_etabs.cli import main  # noqa: E402  (después de ajustar la ruta)

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
