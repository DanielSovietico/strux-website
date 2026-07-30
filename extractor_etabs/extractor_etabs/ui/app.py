"""Arranque de la aplicación de escritorio."""

from __future__ import annotations

import sys
from typing import List, Optional

from ..version import APP_ID, APP_NAME, ORG_NAME, __version__


def main(argv: Optional[List[str]] = None) -> int:
    """Abre la ventana principal. Devuelve el código de salida del proceso."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:      # pragma: no cover - entorno sin Qt
        print("Falta PySide6. Instálalo con:  pip install PySide6",
              file=sys.stderr)
        print(f"({exc})", file=sys.stderr)
        return 2

    from .main_window import MainWindow

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(f"{APP_NAME} {__version__}")
    app.setApplicationVersion(__version__)
    app.setOrganizationName(ORG_NAME)
    app.setDesktopFileName(APP_ID)
    if hasattr(Qt, "AA_DontShowIconsInMenus"):
        app.setAttribute(Qt.AA_DontShowIconsInMenus, False)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
