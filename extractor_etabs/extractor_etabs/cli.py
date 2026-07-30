"""Línea de comandos: la misma extracción sin abrir la ventana.

Sirve para automatizar (procesar varios modelos en lote, dejarlo en una tarea
programada) y para revisar en segundos que un archivo se lee bien:

.. code-block:: text

    python -m extractor_etabs diagnostico
    python -m extractor_etabs offline --e2k modelo.e2k --tabla fuerzas.csv --xlsx salida.xlsx
    python -m extractor_etabs etabs --abrir C:\\modelos\\torre.EDB --todos --xlsx salida.xlsx
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .core import export as export_mod
from .core import strux_payload
from .core.etabs_api import available_backends, platform_supported, unavailable_reason
from .core.extractors import ExtractionOptions
from .core.session import Session
from .core.units import UNIT_CHOICES
from .version import APP_NAME, __version__


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--unidades", default="Ton_m_C",
                        choices=[key for key, _ in UNIT_CHOICES],
                        help="sistema de unidades de salida (por omisión Ton_m_C)")
    parser.add_argument("--deflexiones", action="store_true",
                        help="calcular deflexiones de trabes por doble "
                             "integración de M3/EI")
    parser.add_argument("--e", type=float, default=221359.0,
                        help="módulo de elasticidad para las deflexiones")
    parser.add_argument("--e-unidades", default="kgf/cm2",
                        help="unidades de E (kgf/cm2, MPa, kip/in2…)")
    parser.add_argument("--inercia", type=float, default=1.0,
                        help="factor sobre la inercia bruta (1.0 = Ig)")
    parser.add_argument("--xlsx", help="ruta del libro de Excel a escribir")
    parser.add_argument("--csv", help="carpeta donde escribir un CSV por tabla")
    parser.add_argument("--json", help="ruta del JSON con resultados y modelo")
    parser.add_argument("--puente",
                        help="ruta del JSON con el formato que consume el visor "
                             "de vigas (legacy/Vigas_ETABS_autocontenido.html)")
    parser.add_argument("--silencio", action="store_true",
                        help="no imprimir el registro paso a paso")


def _options_from_args(args: argparse.Namespace) -> ExtractionOptions:
    return ExtractionOptions(
        units_key=args.unidades,
        deflections=bool(getattr(args, "deflexiones", False)),
        e_value=args.e,
        e_units=getattr(args, "e_unidades"),
        inertia_factor=args.inercia,
    )


def _write_outputs(args: argparse.Namespace, session: Session) -> List[str]:
    written: List[str] = []
    result, model = session.result, session.model
    if result is not None:
        if args.xlsx:
            written.append(export_mod.export_xlsx(result, args.xlsx, model))
        if args.csv:
            written.extend(export_mod.export_csv_bundle(result, args.csv))
        if args.json:
            written.append(export_mod.export_json(result, args.json, model))
    if args.puente:
        written.append(strux_payload.write_bridge_json(args.puente, model, result))
    return written


def _run_offline(args: argparse.Namespace) -> int:
    session = Session(on_log=None if args.silencio else lambda m: print("·", m))
    if not args.e2k and not args.tabla:
        print("Indica al menos --e2k o --tabla.", file=sys.stderr)
        return 2
    if args.e2k:
        model = session.load_e2k(args.e2k)
        if model.error:
            print(f"Error en el .e2k: {model.error}", file=sys.stderr)
    if args.tabla:
        for index, path in enumerate(args.tabla):
            result = session.load_table(path, merge=index > 0)
            if result.error:
                print(f"Error en la tabla «{path}»: {result.error}",
                      file=sys.stderr)
    options = _options_from_args(args)
    if options.deflections and session.result is not None:
        if session.model is None:
            print("Para calcular deflexiones hace falta --e2k (dimensiones de "
                  "sección y claros).", file=sys.stderr)
        else:
            session.add_deflections(options)

    from .core.model import ResultSet

    print()
    print(export_mod.summary_text(session.result or ResultSet(source="—"),
                                  session.model))
    for path in _write_outputs(args, session):
        print(f"Escrito: {path}")
    return 0 if (session.result is None or not session.result.error) else 1


def _run_etabs(args: argparse.Namespace) -> int:
    reason = unavailable_reason()
    if reason:
        print(reason, file=sys.stderr)
        return 3
    session = Session(on_log=None if args.silencio else lambda m: print("·", m))
    session.connect()
    if args.abrir:
        session.open_model(args.abrir)
    model = session.read_model(args.unidades)

    options = _options_from_args(args)
    options.run_analysis_if_unlocked = args.correr_analisis
    options.stories = list(args.niveles or [])
    options.frame_forces = not args.sin_fuerzas
    options.displacements = not args.sin_desplazamientos
    options.drifts = not args.sin_derivas
    options.reactions = args.reacciones
    if args.todos:
        options.cases = list(model.load_cases)
        options.combos = list(model.load_combos)
    else:
        options.cases = list(args.casos or [])
        options.combos = list(args.combos or [])
    if not options.all_case_names:
        print("No se indicaron casos: usa --todos, --casos o --combos.",
              file=sys.stderr)
        return 2

    result = session.extract(options)
    print()
    print(export_mod.summary_text(result, model))
    for path in _write_outputs(args, session):
        print(f"Escrito: {path}")
    session.close()
    return 0 if not result.error else 1


def _run_diagnostico(_args: argparse.Namespace) -> int:
    print(f"{APP_NAME} {__version__}")
    print(f"Python              : {sys.version.split()[0]} ({sys.platform})")
    print(f"Plataforma con OAPI : {'sí' if platform_supported() else 'no'}")
    print(f"Enlaces disponibles : {', '.join(available_backends()) or 'ninguno'}")
    try:
        import PySide6
        print(f"PySide6             : {PySide6.__version__}")
    except ImportError:
        print("PySide6             : no instalado (la ventana no abrirá)")
    try:
        import openpyxl
        print(f"openpyxl            : {openpyxl.__version__}")
    except ImportError:
        print("openpyxl            : no instalado (sin exportación a .xlsx)")
    reason = unavailable_reason()
    print(f"OAPI                : {'lista' if not reason else reason}")
    dll = os.environ.get("ETABS_DLL")
    if dll:
        print(f"ETABS_DLL           : {dll}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extractor_etabs",
        description=f"{APP_NAME} {__version__} — extrae momentos, cortantes y "
                    "deformaciones de modelos de ETABS.")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="comando")

    gui = subparsers.add_parser("gui", help="abrir la ventana (comportamiento "
                                            "por omisión)")
    gui.set_defaults(func=lambda _args: _run_gui())

    offline = subparsers.add_parser(
        "offline", help="trabajar con archivos, sin ETABS instalado")
    offline.add_argument("--e2k", help="archivo .e2k / .$et con la geometría")
    offline.add_argument("--tabla", nargs="+",
                         help="una o más tablas exportadas (CSV/TSV/XLSX)")
    _add_common(offline)
    offline.set_defaults(func=_run_offline)

    etabs = subparsers.add_parser(
        "etabs", help="conectarse a ETABS y extraer por la OAPI")
    etabs.add_argument("--abrir", help="modelo a abrir en ETABS antes de extraer")
    etabs.add_argument("--casos", nargs="*", help="casos de carga a extraer")
    etabs.add_argument("--combos", nargs="*", help="combinaciones a extraer")
    etabs.add_argument("--todos", action="store_true",
                       help="todos los casos y combinaciones del modelo")
    etabs.add_argument("--niveles", nargs="*", help="limitar a estos niveles")
    etabs.add_argument("--sin-fuerzas", action="store_true",
                       help="no pedir elementos mecánicos")
    etabs.add_argument("--sin-desplazamientos", action="store_true",
                       help="no pedir desplazamientos de nudos")
    etabs.add_argument("--sin-derivas", action="store_true",
                       help="no pedir derivas de entrepiso")
    etabs.add_argument("--reacciones", action="store_true",
                       help="pedir también las reacciones en la base")
    etabs.add_argument("--correr-analisis", action="store_true",
                       help="correr el análisis si el modelo no está bloqueado")
    _add_common(etabs)
    etabs.set_defaults(func=_run_etabs)

    diag = subparsers.add_parser(
        "diagnostico", help="revisar el entorno (Python, enlaces, OAPI)")
    diag.set_defaults(func=_run_diagnostico)
    return parser


def _run_gui() -> int:
    from .ui.app import main as gui_main
    return gui_main([sys.argv[0]])


def main(argv: Optional[List[str]] = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not args_list:
        return _run_gui()
    args = parser.parse_args(args_list)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\nInterrumpido.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":      # pragma: no cover
    raise SystemExit(main())
