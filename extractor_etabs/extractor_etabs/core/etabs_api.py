"""Puente con la OAPI de ETABS (CSI API v1).

Cubre las tres formas de trabajar con ETABS:

1. **Conectarse a la instancia abierta** — el caso normal: el ingeniero ya tiene
   su modelo en pantalla con el análisis corrido.
2. **Abrir un archivo** — ``.EDB``, ``.E2K``, ``.$ET``, ``.xlsx``… en la instancia
   ya abierta o en una nueva que la aplicación lanza.
3. **Lanzar ETABS** cuando no hay ninguna instancia corriendo.

Soporta los dos enlaces habituales: ``comtypes`` (COM, el recomendado en
Windows) y ``pythonnet`` (cargando ``ETABSv1.dll``). Las dos convenciones de
parámetros por referencia son distintas —comtypes devuelve ``(*salidas, ret)`` y
pythonnet ``(ret, *salidas)``— y aquí se normalizan en un solo lugar
(:meth:`EtabsConnection.call`), que es lo que hace que el resto del código sea
independiente del enlace.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Tipos de salida que se piden a la OAPI (ver docstring de :func:`_placeholders`).
INT = "int"
DBL = "float"
STR = "str"
BOOL = "bool"
INT_ARR = "int[]"
DBL_ARR = "float[]"
STR_ARR = "str[]"
BOOL_ARR = "bool[]"

#: ProgIDs conocidos del ayudante de la API, del más nuevo al más viejo.
HELPER_PROGIDS = ("ETABSv1.Helper", "ETABS2016.Helper", "ETABS2015.Helper")

#: Nombre con el que ETABS se registra para adjuntarse a la instancia abierta.
ETABS_OBJECT = "CSI.ETABS.API.ETABSObject"

#: Extensiones que ``File.OpenFile`` acepta.
OPENABLE_EXTENSIONS = (".edb", ".e2k", ".$et", ".ebd", ".xlsx", ".xls", ".mdb", ".accdb")

# eItemTypeElm
ITEM_OBJECT_ELM = 0
ITEM_ELEMENT = 1
ITEM_GROUP_ELM = 2
ITEM_SELECTION_ELM = 3

#: eFrameDesignOrientation → clasificación interna.
_ORIENTATION = {1: "COLUMN", 2: "BEAM", 3: "BRACE", 4: "OTHER", 5: "OTHER"}


class EtabsError(RuntimeError):
    """Error al hablar con ETABS, con un mensaje pensado para el usuario."""


class EtabsUnavailable(EtabsError):
    """No hay forma de usar la OAPI en esta máquina (plataforma o enlace)."""


def platform_supported() -> bool:
    """La OAPI de ETABS solo existe en Windows."""
    return sys.platform.startswith("win")


def available_backends() -> List[str]:
    """Enlaces instalados y utilizables, en orden de preferencia."""
    found: List[str] = []
    try:
        import comtypes.client  # noqa: F401
        found.append("comtypes")
    except ImportError:
        pass
    try:
        import clr  # noqa: F401
        found.append("pythonnet")
    except ImportError:
        pass
    return found


def unavailable_reason() -> Optional[str]:
    """Explica por qué no se puede usar la OAPI, o ``None`` si sí se puede."""
    if not platform_supported():
        return ("La OAPI de ETABS solo funciona en Windows. En este sistema "
                "puedes trabajar con archivos .e2k y con tablas exportadas, que "
                "dan la misma información sin necesidad de ETABS.")
    if not available_backends():
        return ("Falta el enlace con la API: instala comtypes "
                "(pip install comtypes) o pythonnet (pip install pythonnet).")
    return None


@dataclass
class ProgramInfo:
    name: Optional[str] = None
    version: Optional[str] = None
    level: Optional[str] = None


def _placeholders(backend: str, spec: Sequence[str]) -> List[Any]:
    """Valores iniciales para los parámetros por referencia de la OAPI.

    Los métodos de la CSI API declaran sus salidas ``ByRef``, de modo que hay
    que pasarlas en la llamada. comtypes acepta ``0`` y listas vacías;
    pythonnet exige arreglos de .NET con el tipo correcto.
    """
    if backend == "pythonnet":
        try:
            from System import (  # type: ignore
                Array, Boolean, Double, Int32, String,
            )
        except ImportError:
            # Sin el runtime de .NET no hay nada que tipar: se usan los
            # marcadores simples (es también lo que permite probar el orden de
            # los valores de retorno de pythonnet fuera de Windows).
            return _placeholders("comtypes", spec)

        mapping = {
            INT: lambda: 0,
            DBL: lambda: 0.0,
            STR: lambda: "",
            BOOL: lambda: False,
            INT_ARR: lambda: Array.CreateInstance(Int32, 0),
            DBL_ARR: lambda: Array.CreateInstance(Double, 0),
            STR_ARR: lambda: Array.CreateInstance(String, 0),
            BOOL_ARR: lambda: Array.CreateInstance(Boolean, 0),
        }
        return [mapping[kind]() for kind in spec]

    simple = {INT: 0, DBL: 0.0, STR: "", BOOL: False}
    return [simple[kind] if kind in simple else [] for kind in spec]


def _as_list(value: Any) -> List[Any]:
    """Normaliza un arreglo de la OAPI (tupla, lista o ``System.Array``)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return [value]


class EtabsConnection:
    """Sesión con ETABS. Un objeto por hilo: COM es *apartment threaded*."""

    def __init__(self, backend: Optional[str] = None,
                 dll_path: Optional[str] = None) -> None:
        self.backend: Optional[str] = backend
        self.dll_path = dll_path or os.environ.get("ETABS_DLL")
        self._etabs: Any = None
        self._sap: Any = None
        self._helper: Any = None
        self._started_by_us = False
        self._com_initialized = False
        self.warnings: List[str] = []

    # ── ciclo de vida ───────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._sap is not None

    @property
    def sap_model(self) -> Any:
        if self._sap is None:
            raise EtabsError("No hay conexión con ETABS.")
        return self._sap

    def initialize_thread(self) -> None:
        """Inicializa COM en el hilo actual (necesario fuera del hilo principal)."""
        if self._com_initialized:
            return
        try:
            import comtypes
            comtypes.CoInitialize()
            self._com_initialized = True
        except Exception:            # pragma: no cover - sin COM no hace falta
            pass

    def uninitialize_thread(self) -> None:
        if not self._com_initialized:
            return
        try:
            import comtypes
            comtypes.CoUninitialize()
        except Exception:            # pragma: no cover
            pass
        self._com_initialized = False

    def _helper_object(self) -> Tuple[str, Any]:
        """Crea el ``cHelper`` con el primer enlace disponible."""
        reason = unavailable_reason()
        if reason:
            raise EtabsUnavailable(reason)

        backends = [self.backend] if self.backend else available_backends()
        errors: List[str] = []
        for backend in backends:
            try:
                if backend == "comtypes":
                    return backend, self._helper_comtypes()
                if backend == "pythonnet":
                    return backend, self._helper_pythonnet()
            except Exception as exc:
                errors.append(f"{backend}: {exc}")
        raise EtabsUnavailable(
            "No se pudo cargar la API de ETABS. " + " · ".join(errors) +
            ". Revisa que ETABS esté instalado y que Python sea de la misma "
            "arquitectura (64 bits).")

    def _helper_comtypes(self) -> Any:
        import comtypes.client as client

        self.initialize_thread()
        last: Optional[Exception] = None
        for progid in HELPER_PROGIDS:
            try:
                helper = client.CreateObject(progid)
            except Exception as exc:
                last = exc
                continue
            try:
                import comtypes.gen.ETABSv1 as etabs_ns  # type: ignore
                helper = helper.QueryInterface(etabs_ns.cHelper)
            except Exception:
                pass          # algunas versiones ya devuelven la interfaz final
            return helper
        raise EtabsError(f"No se encontró el ayudante de la API ({last}).")

    def _helper_pythonnet(self) -> Any:
        import clr  # type: ignore

        dll = self.dll_path
        if not dll:
            for candidate in (
                r"C:\Program Files\Computers and Structures\ETABS 22\ETABSv1.dll",
                r"C:\Program Files\Computers and Structures\ETABS 21\ETABSv1.dll",
                r"C:\Program Files\Computers and Structures\ETABS 20\ETABSv1.dll",
                r"C:\Program Files\Computers and Structures\ETABS 19\ETABSv1.dll",
            ):
                if os.path.isfile(candidate):
                    dll = candidate
                    break
        if not dll or not os.path.isfile(dll):
            raise EtabsError(
                "No se encontró ETABSv1.dll. Indica su ruta en la variable de "
                "entorno ETABS_DLL.")
        clr.AddReference(dll)
        from ETABSv1 import cHelper, Helper  # type: ignore
        return cHelper(Helper())

    def attach(self) -> ProgramInfo:
        """Se adjunta a la instancia de ETABS que ya está abierta."""
        backend, helper = self._helper_object()
        try:
            etabs = helper.GetObject(ETABS_OBJECT)
        except Exception as exc:
            raise EtabsError(
                "No se encontró una instancia de ETABS abierta. Abre ETABS con "
                "tu modelo y vuelve a intentar, o usa «Abrir modelo…» para que "
                "la aplicación lo lance.") from exc
        if etabs is None:
            raise EtabsError("ETABS respondió vacío al adjuntarse.")
        self.backend, self._helper, self._etabs = backend, helper, etabs
        self._sap = etabs.SapModel
        self._started_by_us = False
        return self.program_info()

    def launch(self, exe_path: Optional[str] = None,
               visible: bool = True) -> ProgramInfo:
        """Lanza una instancia nueva de ETABS y se conecta a ella."""
        backend, helper = self._helper_object()
        try:
            if exe_path:
                etabs = helper.CreateObject(exe_path)
            else:
                etabs = helper.CreateObjectProgID(ETABS_OBJECT)
        except Exception as exc:
            raise EtabsError(
                "No se pudo iniciar ETABS. Si tienes varias versiones "
                "instaladas, indica la ruta de ETABS.exe.") from exc
        ret = etabs.ApplicationStart()
        if ret not in (0, None):
            raise EtabsError(f"ETABS no terminó de iniciar (código {ret}).")
        self.backend, self._helper, self._etabs = backend, helper, etabs
        self._sap = etabs.SapModel
        self._started_by_us = True
        if not visible:
            try:
                self._sap.SetPresentUnits(12)
            except Exception:
                pass
        return self.program_info()

    def connect(self) -> ProgramInfo:
        """Se adjunta si hay instancia abierta; si no, lanza ETABS."""
        try:
            return self.attach()
        except EtabsUnavailable:
            raise
        except EtabsError:
            return self.launch()

    def open_model(self, path: str) -> None:
        """Abre un modelo en la instancia conectada."""
        if not os.path.isfile(path):
            raise EtabsError(f"No existe el archivo: {path}")
        ext = os.path.splitext(path)[1].lower()
        if ext not in OPENABLE_EXTENSIONS:
            raise EtabsError(
                f"ETABS no abre archivos «{ext}». Extensiones válidas: "
                + ", ".join(OPENABLE_EXTENSIONS))
        if not self.connected:
            self.connect()
        ret = self.sap_model.File.OpenFile(os.path.abspath(path))
        if ret not in (0, None):
            raise EtabsError(
                f"ETABS no pudo abrir «{os.path.basename(path)}» (código {ret}). "
                "Suele ocurrir cuando el archivo lo creó una versión más nueva "
                "de ETABS o está abierto en otra instancia.")

    def disconnect(self, close_etabs: Optional[bool] = None) -> None:
        """Suelta la conexión; cierra ETABS solo si esta aplicación lo abrió."""
        should_close = self._started_by_us if close_etabs is None else close_etabs
        if should_close and self._etabs is not None:
            try:
                self._etabs.ApplicationExit(False)
            except Exception:
                pass
        self._sap = self._etabs = self._helper = None
        self._started_by_us = False
        self.uninitialize_thread()

    # ── llamada normalizada ─────────────────────────────────────────────────

    def call(self, func: Callable[..., Any], in_args: Sequence[Any] = (),
             out_spec: Sequence[str] = (), check: bool = True,
             what: str = "") -> List[Any]:
        """Invoca un método de la OAPI y devuelve solo sus salidas.

        Resuelve las dos convenciones de orden (``ret`` al final en comtypes, al
        principio en pythonnet) y verifica el código de retorno.
        """
        args = list(in_args) + _placeholders(self.backend or "comtypes", out_spec)
        try:
            raw = func(*args)
        except TypeError:
            # Algunos enlaces exponen el método sin los parámetros de salida.
            raw = func(*in_args)
        except Exception as exc:
            raise EtabsError(
                f"ETABS rechazó la llamada {what or getattr(func, '__name__', '')}: "
                f"{exc}") from exc

        if not isinstance(raw, (list, tuple)):
            ret, outs = raw, []
        else:
            values = list(raw)
            if self.backend == "pythonnet":
                ret, outs = values[0], values[1:]
            else:
                ret, outs = values[-1], values[:-1]
            # Red de seguridad si el enlace invierte el orden esperado.
            if not isinstance(ret, int) and len(values) == len(out_spec) + 1:
                other = values[0] if self.backend != "pythonnet" else values[-1]
                if isinstance(other, int):
                    ret = other
                    outs = values[1:] if self.backend != "pythonnet" else values[:-1]

        if check and isinstance(ret, int) and ret != 0:
            raise EtabsError(
                f"ETABS devolvió el código {ret} en {what or 'la consulta'}.")
        return outs

    def try_call(self, func: Callable[..., Any], in_args: Sequence[Any] = (),
                 out_spec: Sequence[str] = (), what: str = ""
                 ) -> Optional[List[Any]]:
        """Como :meth:`call`, pero anota la falla y sigue en lugar de abortar."""
        try:
            return self.call(func, in_args, out_spec, check=True, what=what)
        except EtabsError as exc:
            self.warnings.append(str(exc))
            return None

    # ── consultas básicas ───────────────────────────────────────────────────

    def program_info(self) -> ProgramInfo:
        outs = self.try_call(self.sap_model.GetProgramInfo, (), (STR, STR, STR),
                             what="información del programa")
        if not outs:
            return ProgramInfo(name="ETABS")
        return ProgramInfo(name=str(outs[0]) or "ETABS",
                           version=str(outs[1]) or None,
                           level=str(outs[2]) or None)

    def model_filename(self, include_path: bool = True) -> Optional[str]:
        try:
            name = self.sap_model.GetModelFilename(include_path)
        except Exception:
            try:
                name = self.sap_model.GetModelFilename()
            except Exception:
                return None
        text = str(name or "").strip()
        return text or None

    def is_locked(self) -> Optional[bool]:
        try:
            return bool(self.sap_model.GetModelIsLocked())
        except Exception:
            return None

    def present_units(self) -> Optional[int]:
        try:
            return int(self.sap_model.GetPresentUnits())
        except Exception:
            return None

    def set_units(self, code: int) -> None:
        self.try_call(self.sap_model.SetPresentUnits, (int(code),), (),
                      what="fijar unidades")

    def run_analysis(self) -> None:
        """Corre el análisis (necesario si el modelo no está bloqueado)."""
        self.call(self.sap_model.Analyze.RunAnalysis, (), (),
                  what="correr el análisis")

    def name_list(self, owner: Any, what: str) -> List[str]:
        """``GetNameList`` genérico (casos, combos, barras, secciones…)."""
        outs = self.try_call(owner.GetNameList, (), (INT, STR_ARR), what=what)
        if not outs:
            return []
        return [str(n) for n in _as_list(outs[1]) if str(n)]

    def load_cases(self) -> List[str]:
        return self.name_list(self.sap_model.LoadCases, "lista de casos de carga")

    def load_combos(self) -> List[str]:
        return self.name_list(self.sap_model.RespCombo, "lista de combinaciones")

    def load_patterns(self) -> List[str]:
        return self.name_list(self.sap_model.LoadPatterns, "lista de patrones")

    # ── selección de casos para salida ──────────────────────────────────────

    def select_output(self, cases: Sequence[str], combos: Sequence[str]) -> List[str]:
        """Deja seleccionados para salida exactamente los casos/combos dados.

        Devuelve la lista de nombres que ETABS aceptó; los rechazados quedan en
        ``warnings`` para que la interfaz los muestre.
        """
        setup = self.sap_model.Results.Setup
        self.try_call(setup.DeselectAllCasesAndCombosForOutput, (), (),
                      what="limpiar la selección de salida")
        accepted: List[str] = []
        for name in cases:
            if self.try_call(setup.SetCaseSelectedForOutput, (name, True), (),
                             what=f"seleccionar el caso «{name}»") is not None:
                accepted.append(name)
        for name in combos:
            if self.try_call(setup.SetComboSelectedForOutput, (name, True), (),
                             what=f"seleccionar la combinación «{name}»") is not None:
                accepted.append(name)
        return accepted

    # ── tablas genéricas (DatabaseTables) ───────────────────────────────────

    def table(self, table_key: str, cases: Sequence[str] = ()
              ) -> Tuple[List[str], List[List[str]]]:
        """Lee cualquier tabla de la base de datos del modelo.

        Es la vía de escape para todo lo que no tiene método propio en la OAPI
        (por ejemplo *Diaphragm Center of Mass Displacements*).
        """
        db = self.sap_model.DatabaseTables
        if cases:
            self.try_call(db.SetLoadCasesSelectedForDisplay,
                          (list(cases),), (), what="seleccionar casos de la tabla")
        outs = self.call(
            db.GetTableForDisplayArray, (table_key, [], ""),
            (INT, STR_ARR, INT, STR_ARR), check=True,
            what=f"leer la tabla «{table_key}»")
        # Salidas: TableVersion, FieldsKeysIncluded, NumberRecords, TableData.
        # ``FieldKeyList`` también se declara ByRef, así que algunos enlaces lo
        # devuelven como primera salida: se detecta por la cantidad de valores.
        if len(outs) >= 5:
            outs = outs[1:]
        fields = [str(f) for f in _as_list(outs[1])]
        records = int(outs[2] or 0)
        flat = [str(v) for v in _as_list(outs[3])]
        if not fields:
            return [], []
        width = len(fields)
        rows = [flat[i * width:(i + 1) * width] for i in range(records)]
        return fields, [r for r in rows if len(r) == width]

    # ── geometría ───────────────────────────────────────────────────────────

    def stories(self) -> List[Tuple[str, Optional[float], Optional[float]]]:
        """``(nombre, cota, altura)`` de cada nivel, del más bajo al más alto."""
        spec = (INT, STR_ARR, DBL_ARR, DBL_ARR, BOOL_ARR, STR_ARR, BOOL_ARR, DBL_ARR)
        story = self.sap_model.Story
        for method_name in ("GetStories_2", "GetStories"):
            method = getattr(story, method_name, None)
            if method is None:
                continue
            outs = self.try_call(method, (), spec, what="niveles del modelo")
            if outs:
                names = [str(n) for n in _as_list(outs[1])]
                elevations = [float(v) for v in _as_list(outs[2])]
                heights = [float(v) for v in _as_list(outs[3])]
                if names:
                    return [(names[i],
                             elevations[i] if i < len(elevations) else None,
                             heights[i] if i < len(heights) else None)
                            for i in range(len(names))]
        # Última opción: nombres y cotas una por una.
        names = self.name_list(story, "niveles del modelo")
        result: List[Tuple[str, Optional[float], Optional[float]]] = []
        for name in names:
            outs = self.try_call(story.GetElevation, (name,), (DBL,),
                                 what=f"cota del nivel «{name}»")
            result.append((name, float(outs[0]) if outs else None, None))
        return result

    def grid_lines(self) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Ejes cartesianos ``(etiqueta, ordenada)`` en X y en Y."""
        grid = getattr(self.sap_model, "GridSys", None)
        if grid is None:
            return [], []
        systems = self.name_list(grid, "sistemas de ejes")
        method = getattr(grid, "GetGridSysCartesian", None)
        if method is None or not systems:
            self.warnings.append(
                "Esta versión de la API no expone las ordenadas de los ejes: "
                "las barras se identifican por coordenadas.")
            return [], []
        spec = (DBL, DBL, DBL, INT, INT, STR_ARR, STR_ARR, DBL_ARR, DBL_ARR,
                BOOL_ARR, BOOL_ARR, STR_ARR, STR_ARR)
        gx: List[Tuple[str, float]] = []
        gy: List[Tuple[str, float]] = []
        for system in systems:
            outs = self.try_call(method, (system,), spec,
                                 what=f"ejes del sistema «{system}»")
            if not outs:
                continue
            ids_x = [str(v) for v in _as_list(outs[5])]
            ids_y = [str(v) for v in _as_list(outs[6])]
            ord_x = [float(v) for v in _as_list(outs[7])]
            ord_y = [float(v) for v in _as_list(outs[8])]
            gx.extend(zip(ids_x, ord_x))
            gy.extend(zip(ids_y, ord_y))
        return gx, gy

    def frame_names(self) -> List[str]:
        return self.name_list(self.sap_model.FrameObj, "lista de barras")

    def frame_geometry(self, name: str) -> Dict[str, Any]:
        """Nivel, etiqueta, sección, tipo y coordenadas de los extremos."""
        frame_obj = self.sap_model.FrameObj
        data: Dict[str, Any] = {"name": name}

        outs = self.try_call(frame_obj.GetLabelFromName, (name,), (STR, STR),
                             what=f"etiqueta de «{name}»")
        if outs:
            data["label"] = str(outs[0]) or None
            data["story"] = str(outs[1]) or None

        outs = self.try_call(frame_obj.GetSection, (name,), (STR, STR),
                             what=f"sección de «{name}»")
        if outs:
            data["section"] = str(outs[0]) or None

        orientation = self.try_call(frame_obj.GetDesignOrientation, (name,), (INT,),
                                    what=f"tipo de «{name}»")
        if orientation:
            data["kind"] = _ORIENTATION.get(int(orientation[0]), "OTHER")

        outs = self.try_call(frame_obj.GetPoints, (name,), (STR, STR),
                             what=f"nudos de «{name}»")
        if outs:
            data["point_i"], data["point_j"] = str(outs[0]), str(outs[1])
            for suffix, point in (("i", data["point_i"]), ("j", data["point_j"])):
                coords = self.try_call(
                    self.sap_model.PointObj.GetCoordCartesian, (point,),
                    (DBL, DBL, DBL), what=f"coordenadas del nudo «{point}»")
                if coords:
                    data[f"x{suffix}"] = float(coords[0])
                    data[f"y{suffix}"] = float(coords[1])
                    data[f"z{suffix}"] = float(coords[2])
        return data

    def rectangular_section(self, name: str) -> Optional[Dict[str, Any]]:
        """Dimensiones de una sección rectangular (``T3`` peralte, ``T2`` ancho)."""
        prop = self.sap_model.PropFrame
        outs = self.try_call(prop.GetRectangle, (name,),
                             (STR, STR, DBL, DBL, INT, STR, STR),
                             what=f"dimensiones de la sección «{name}»")
        if not outs:
            return None
        return {"material": str(outs[1]) or None,
                "h": float(outs[2]), "b": float(outs[3]),
                "shape": "Rectangular"}

    def section_names(self) -> List[str]:
        return self.name_list(self.sap_model.PropFrame, "lista de secciones")

    # ── resultados ──────────────────────────────────────────────────────────

    def frame_force(self, name: str, item_type: int = ITEM_OBJECT_ELM
                    ) -> Dict[str, List[Any]]:
        """``Results.FrameForce`` de una barra, ya desempacado por columna."""
        spec = (INT, STR_ARR, DBL_ARR, STR_ARR, DBL_ARR, STR_ARR, STR_ARR,
                DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR)
        outs = self.call(self.sap_model.Results.FrameForce, (name, item_type),
                         spec, what=f"fuerzas de la barra «{name}»")
        keys = ("obj", "obj_sta", "elm", "elm_sta", "case", "step_type",
                "step_num", "P", "V2", "V3", "T", "M2", "M3")
        return {key: _as_list(outs[i + 1]) for i, key in enumerate(keys)}

    def joint_displacements(self, name: str, item_type: int = ITEM_OBJECT_ELM
                            ) -> Dict[str, List[Any]]:
        """``Results.JointDispl`` de un nudo o grupo de nudos."""
        spec = (INT, STR_ARR, STR_ARR, STR_ARR, STR_ARR, DBL_ARR,
                DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR)
        outs = self.call(self.sap_model.Results.JointDispl, (name, item_type),
                         spec, what=f"desplazamientos de «{name}»")
        keys = ("obj", "elm", "case", "step_type", "step_num",
                "U1", "U2", "U3", "R1", "R2", "R3")
        return {key: _as_list(outs[i + 1]) for i, key in enumerate(keys)}

    def story_drifts(self) -> Dict[str, List[Any]]:
        spec = (INT, STR_ARR, STR_ARR, STR_ARR, DBL_ARR, STR_ARR, DBL_ARR,
                STR_ARR, DBL_ARR, DBL_ARR, DBL_ARR)
        outs = self.call(self.sap_model.Results.StoryDrifts, (), spec,
                         what="derivas de entrepiso")
        keys = ("story", "case", "step_type", "step_num", "direction", "drift",
                "label", "x", "y", "z")
        return {key: _as_list(outs[i + 1]) for i, key in enumerate(keys)}

    def base_reactions(self) -> Dict[str, List[Any]]:
        spec = (INT, STR_ARR, STR_ARR, DBL_ARR, DBL_ARR, DBL_ARR, DBL_ARR,
                DBL_ARR, DBL_ARR, DBL_ARR, DBL, DBL, DBL)
        outs = self.call(self.sap_model.Results.BaseReact, (), spec,
                         what="reacciones en la base")
        keys = ("case", "step_type", "step_num", "FX", "FY", "FZ",
                "MX", "MY", "MZ")
        return {key: _as_list(outs[i + 1]) for i, key in enumerate(keys)}

    def point_names_for_story(self, story: str) -> List[str]:
        """Nudos que pertenecen a un nivel (para desplazamientos por piso)."""
        point_obj = self.sap_model.PointObj
        names = self.name_list(point_obj, "lista de nudos")
        if not names:
            return []
        selected: List[str] = []
        for name in names:
            outs = self.try_call(point_obj.GetLabelFromName, (name,), (STR, STR),
                                 what=f"nivel del nudo «{name}»")
            if outs and str(outs[1]) == story:
                selected.append(name)
        return selected
