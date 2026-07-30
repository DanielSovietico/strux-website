#!/usr/bin/env python3
"""Empaqueta la aplicación con PyInstaller.

    python empaquetar.py                 → dist/ExtractorETABS/ (arranque rápido)
    python empaquetar.py --un-archivo    → dist/ExtractorETABS.exe (un solo archivo)

Compila en Windows para obtener un ``.exe``; PyInstaller no hace compilación
cruzada. ``comtypes`` se toma del entorno de la máquina donde se compile: si no
está instalado, el ejecutable abre igual pero sin la ruta OAPI.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
NOMBRE = "ExtractorETABS"


def main() -> int:
    parser = argparse.ArgumentParser(description="Empaqueta el Extractor ETABS.")
    parser.add_argument("--un-archivo", action="store_true",
                        help="un solo ejecutable en vez de una carpeta")
    parser.add_argument("--con-consola", action="store_true",
                        help="dejar la consola visible (útil para depurar)")
    parser.add_argument("--limpio", action="store_true",
                        help="borrar la caché de PyInstaller antes de compilar")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Falta PyInstaller:  pip install pyinstaller", file=sys.stderr)
        return 2

    separador = ";" if os.name == "nt" else ":"
    orden = [
        sys.executable, "-m", "PyInstaller",
        "--name", NOMBRE,
        "--noconfirm",
        "--windowed" if not args.con_consola else "--console",
        "--onefile" if args.un_archivo else "--onedir",
        # Datos que la aplicación ofrece al usuario.
        "--add-data", f"ejemplos{separador}ejemplos",
        "--add-data", f"legacy{separador}legacy",
        "--add-data", f"docs{separador}docs",
        # Módulos que se cargan de forma diferida.
        "--hidden-import", "extractor_etabs.ui.main_window",
        "--collect-submodules", "extractor_etabs",
        # Qt trae mucho que esta aplicación no usa.
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "tkinter",
        "run.py",
    ]
    if args.limpio:
        orden.insert(3, "--clean")

    print(" ".join(orden))
    completado = subprocess.run(orden, cwd=RAIZ, check=False)
    if completado.returncode == 0:
        destino = (os.path.join("dist", NOMBRE + (".exe" if os.name == "nt" else ""))
                   if args.un_archivo else os.path.join("dist", NOMBRE))
        print(f"\nListo: {os.path.join(RAIZ, destino)}")
    return completado.returncode


if __name__ == "__main__":
    raise SystemExit(main())
