"""ETABS simulado para probar la ruta OAPI sin Windows ni licencia.

Reproduce la parte del ``SapModel`` que usa la aplicación, con la convención de
comtypes (los parámetros por referencia se devuelven en orden y el código de
retorno va **al final**) y, opcionalmente, con la de pythonnet (el código de
retorno va **al principio**). Así se prueban de verdad el desempacado de
:meth:`EtabsConnection.call` y los extractores completos.

El modelo simulado es un marco de dos niveles y tres trabes por nivel, con dos
combinaciones, y todos los valores son inventados a propósito y fáciles de
verificar en las pruebas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

STORIES = [("Nivel 1", 3.5, 3.5), ("Azotea", 7.0, 3.5)]
GRID_X = [("A", 0.0), ("B", 6.0), ("C", 12.0)]
GRID_Y = [("1", 0.0)]
SECTIONS = {"V-30X60": (0.60, 0.30, "C250"), "C-40X40": (0.40, 0.40, "C250")}
CASES = ["CM", "CV"]
COMBOS = ["1.3CM+1.5CV", "CM+CV"]

#: nombre → (etiqueta, nivel, sección, orientación, nudo i, nudo j)
FRAMES: Dict[str, Tuple[str, str, str, int, str, str]] = {
    "1": ("B1", "Azotea", "V-30X60", 2, "p1", "p2"),
    "2": ("B2", "Azotea", "V-30X60", 2, "p2", "p3"),
    "3": ("B1", "Nivel 1", "V-30X60", 2, "p4", "p5"),
    "4": ("C1", "Azotea", "C-40X40", 1, "p1", "p4"),
}
POINTS = {
    "p1": (0.0, 0.0, 7.0), "p2": (6.0, 0.0, 7.0), "p3": (12.0, 0.0, 7.0),
    "p4": (0.0, 0.0, 3.5), "p5": (6.0, 0.0, 3.5),
}

#: Estaciones y momentos por barra y caso (V2 = derivada aproximada de M3).
STATIONS = [0.0, 1.5, 3.0, 4.5, 6.0]


def _forces_for(frame: str, case: str) -> Tuple[List[float], List[float], List[float]]:
    factor = 1.0 if case == "1.3CM+1.5CV" else 0.6
    moments = [-9.0, 4.0, 7.5, 4.0, -9.0]
    shears = [11.0, 5.5, 0.0, -5.5, -11.0]
    return (STATIONS,
            [m * factor for m in moments],
            [v * factor for v in shears])


class _Sub:
    """Contenedor con métodos asignables (imita los subobjetos de la OAPI)."""

    def __init__(self, **methods: Any) -> None:
        for name, method in methods.items():
            setattr(self, name, method)


class FakeSapModel:
    """``SapModel`` simulado. ``ret_first=True`` imita a pythonnet."""

    def __init__(self, ret_first: bool = False, locked: bool = True,
                 fail_group: bool = False, no_grids: bool = False) -> None:
        self.ret_first = ret_first
        self.locked = locked
        self.fail_group = fail_group
        self.no_grids = no_grids
        self.units = 12
        self.selected: List[str] = []
        self.analysis_runs = 0

        self.Story = _Sub(GetStories_2=self._get_stories,
                          GetNameList=self._story_name_list,
                          GetElevation=self._story_elevation)
        self.GridSys = _Sub(GetNameList=self._grid_name_list,
                            GetGridSysCartesian=self._grid_cartesian)
        self.LoadCases = _Sub(GetNameList=lambda *a: self._names(CASES))
        self.RespCombo = _Sub(GetNameList=lambda *a: self._names(COMBOS))
        self.LoadPatterns = _Sub(GetNameList=lambda *a: self._names(CASES))
        self.PropFrame = _Sub(GetNameList=lambda *a: self._names(list(SECTIONS)),
                              GetRectangle=self._get_rectangle)
        self.FrameObj = _Sub(GetNameList=lambda *a: self._names(list(FRAMES)),
                             GetLabelFromName=self._label_from_name,
                             GetSection=self._get_section,
                             GetDesignOrientation=self._orientation,
                             GetPoints=self._get_points)
        self.PointObj = _Sub(GetCoordCartesian=self._coord,
                             GetNameList=lambda *a: self._names(list(POINTS)),
                             GetLabelFromName=self._point_label)
        self.Results = _Sub(
            FrameForce=self._frame_force,
            JointDispl=self._joint_displ,
            StoryDrifts=self._story_drifts,
            BaseReact=self._base_react,
            Setup=_Sub(
                DeselectAllCasesAndCombosForOutput=self._deselect,
                SetCaseSelectedForOutput=self._select,
                SetComboSelectedForOutput=self._select))
        self.Analyze = _Sub(RunAnalysis=self._run_analysis)
        self.File = _Sub(OpenFile=self._open_file)
        self.DatabaseTables = _Sub(
            GetTableForDisplayArray=self._table,
            SetLoadCasesSelectedForDisplay=lambda *a: self._pack([]))

    # ── utilidades ──
    def _pack(self, outs: Sequence[Any], ret: int = 0) -> Any:
        values = list(outs)
        if not values:
            return ret
        return tuple([ret] + values) if self.ret_first else tuple(values + [ret])

    def _names(self, names: Sequence[str]) -> Any:
        return self._pack([len(names), list(names)])

    # ── información general ──
    def GetProgramInfo(self, *args: Any) -> Any:
        return self._pack(["ETABS", "22.2.0", "Ultimate"])

    def GetModelFilename(self, include_path: bool = True) -> str:
        return r"C:\modelos\torre.EDB" if include_path else "torre.EDB"

    def GetModelIsLocked(self) -> bool:
        return self.locked

    def GetPresentUnits(self) -> int:
        return self.units

    def SetPresentUnits(self, code: int) -> int:
        self.units = int(code)
        return 0

    def _run_analysis(self, *args: Any) -> int:
        self.analysis_runs += 1
        self.locked = True
        return 0

    def _open_file(self, path: str) -> int:
        self.opened = path
        return 0

    # ── geometría ──
    def _get_stories(self, *args: Any) -> Any:
        names = [s[0] for s in STORIES]
        return self._pack([len(names), names, [s[1] for s in STORIES],
                           [s[2] for s in STORIES], [True] * len(names),
                           [""] * len(names), [False] * len(names),
                           [0.0] * len(names)])

    def _story_name_list(self, *args: Any) -> Any:
        return self._names([s[0] for s in STORIES])

    def _story_elevation(self, name: str, *args: Any) -> Any:
        elevation = dict((s[0], s[1]) for s in STORIES).get(name, 0.0)
        return self._pack([elevation])

    def _grid_name_list(self, *args: Any) -> Any:
        return self._names([] if self.no_grids else ["GLOBAL"])

    def _grid_cartesian(self, name: str, *args: Any) -> Any:
        return self._pack([
            0.0, 0.0, 0.0, len(GRID_X), len(GRID_Y),
            [g[0] for g in GRID_X], [g[0] for g in GRID_Y],
            [g[1] for g in GRID_X], [g[1] for g in GRID_Y],
            [True] * len(GRID_X), [True] * len(GRID_Y),
            ["End"] * len(GRID_X), ["End"] * len(GRID_Y)])

    def _get_rectangle(self, name: str, *args: Any) -> Any:
        if name not in SECTIONS:
            return self._pack(["", "", 0.0, 0.0, 0, "", ""], ret=1)
        h, b, material = SECTIONS[name]
        return self._pack(["", material, h, b, 0, "", ""])

    def _label_from_name(self, name: str, *args: Any) -> Any:
        data = FRAMES.get(name)
        if data is None:
            return self._pack(["", ""], ret=1)
        return self._pack([data[0], data[1]])

    def _get_section(self, name: str, *args: Any) -> Any:
        return self._pack([FRAMES[name][2], ""])

    def _orientation(self, name: str, *args: Any) -> Any:
        return self._pack([FRAMES[name][3]])

    def _get_points(self, name: str, *args: Any) -> Any:
        return self._pack([FRAMES[name][4], FRAMES[name][5]])

    def _coord(self, name: str, *args: Any) -> Any:
        x, y, z = POINTS[name]
        return self._pack([x, y, z])

    def _point_label(self, name: str, *args: Any) -> Any:
        story = "Azotea" if POINTS[name][2] > 3.5 else "Nivel 1"
        return self._pack([name, story])

    # ── selección de salida ──
    def _deselect(self, *args: Any) -> int:
        self.selected.clear()
        return 0

    def _select(self, name: str, selected: bool = True, *args: Any) -> int:
        if name not in CASES + COMBOS:
            return 1
        self.selected.append(name)
        return 0

    # ── resultados ──
    def _frame_force(self, name: str, item_type: int, *args: Any) -> Any:
        if item_type == 2:                      # grupo
            if self.fail_group:
                return self._pack([0] + [[]] * 13, ret=1)
            frames = list(FRAMES)
        else:
            if name not in FRAMES:
                return self._pack([0] + [[]] * 13, ret=1)
            frames = [name]

        obj, sta, case, step, p, v2, v3, t, m2, m3 = ([] for _ in range(10))
        for frame in frames:
            for combo in self.selected:
                stations, moments, shears = _forces_for(frame, combo)
                for index, station in enumerate(stations):
                    obj.append(frame)
                    sta.append(station)
                    case.append(combo)
                    step.append("")
                    p.append(0.0)
                    v2.append(shears[index])
                    v3.append(0.0)
                    t.append(0.0)
                    m2.append(0.0)
                    m3.append(moments[index])
        return self._pack([len(obj), obj, sta, obj, sta, case, step,
                           [0.0] * len(obj), p, v2, v3, t, m2, m3])

    def _joint_displ(self, name: str, item_type: int, *args: Any) -> Any:
        points = list(POINTS) if item_type == 2 else [name]
        obj, case, step, u1, u2, u3, r1, r2, r3 = ([] for _ in range(9))
        for point in points:
            if point not in POINTS:
                continue
            for combo in self.selected:
                obj.append(point)
                case.append(combo)
                step.append("")
                u1.append(0.012)
                u2.append(0.0)
                u3.append(-0.004)
                r1.append(0.0)
                r2.append(0.0006)
                r3.append(0.0)
        return self._pack([len(obj), obj, obj, case, step, [0.0] * len(obj),
                           u1, u2, u3, r1, r2, r3])

    def _story_drifts(self, *args: Any) -> Any:
        stories, cases, steps, nums, dirs, drifts, labels, xs, ys, zs = (
            [] for _ in range(10))
        for story, elevation, _ in STORIES:
            for combo in self.selected:
                stories.append(story)
                cases.append(combo)
                steps.append("Max")
                nums.append(0.0)
                dirs.append("X")
                drifts.append(0.0032)
                labels.append("p1")
                xs.append(0.0)
                ys.append(0.0)
                zs.append(elevation)
        return self._pack([len(stories), stories, cases, steps, nums, dirs,
                           drifts, labels, xs, ys, zs])

    def _base_react(self, *args: Any) -> Any:
        cases, steps, nums = [], [], []
        fx, fy, fz, mx, my, mz = ([] for _ in range(6))
        for combo in self.selected:
            cases.append(combo)
            steps.append("")
            nums.append(0.0)
            fx.append(120.0)
            fy.append(0.0)
            fz.append(-980.0)
            mx.append(0.0)
            my.append(-3400.0)
            mz.append(0.0)
        return self._pack([len(cases), cases, steps, nums, fx, fy, fz,
                           mx, my, mz, 0.0, 0.0, 0.0])

    def _table(self, key: str, fields: Any, group: str, *args: Any) -> Any:
        columnas = ["Story", "Drift"]
        datos = ["Azotea", "0.0032", "Nivel 1", "0.0041"]
        return self._pack([1, columnas, len(datos) // len(columnas), datos])


class FakeEtabsObject:
    """Objeto de aplicación: lo que devuelve ``helper.GetObject``."""

    def __init__(self, sap_model: FakeSapModel) -> None:
        self.SapModel = sap_model
        self.started = False
        self.exited = False

    def ApplicationStart(self) -> int:
        self.started = True
        return 0

    def ApplicationExit(self, save: bool) -> int:
        self.exited = True
        return 0


def make_connection(ret_first: bool = False, **kwargs: Any):
    """Devuelve una :class:`EtabsConnection` ya enganchada al ETABS simulado."""
    from extractor_etabs.core.etabs_api import EtabsConnection

    sap = FakeSapModel(ret_first=ret_first, **kwargs)
    connection = EtabsConnection(backend="pythonnet" if ret_first else "comtypes")
    connection._etabs = FakeEtabsObject(sap)       # noqa: SLF001 (es una prueba)
    connection._sap = sap                          # noqa: SLF001
    return connection, sap
