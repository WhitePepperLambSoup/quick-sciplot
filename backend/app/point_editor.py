"""Drag-to-correct data points.

The renderer exports the data marks it drew (line vertices, scatter offsets,
bar values) together with each axes' geometry in the saved image.  This module
maps those marks back to the dataset rows they came from, so the preview can
let the user drag a point and have the change written to the data:

* a mark matches a pair of columns when every one of its points is found as a
  row with those (x, y) values; each point is then bound to a distinct row;
* numeric axes are compared with a tight relative tolerance, categorical axes
  through the tick/category labels, date axes as Matplotlib date numbers;
* only numeric, linear/log axes of a matched mark are editable.

Corrections are never written in place: :func:`apply_cell_edits` returns a new
frame plus a log of every changed cell, and the caller stores it as a new
dataset version whose provenance records the parent and the full edit history.
"""

import ast
import base64
import json
import math
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data_loader import DataError

MAX_SET_POINTS = 2000
MAX_TOTAL_POINTS = 5000
MAX_SETS = 200
MAX_EDITS = 5000
MAX_PROVENANCE_EDITS = 20000
MAX_COLUMN_PAIRS = 60
REL_TOLERANCE = 1e-9
DATE_TOLERANCE = 1e-6  # days (~0.1 s)
CATEGORY_SNAP = 0.45  # how far a mark may sit from its category (jitter / dodge)
INDEX_COLUMN = "__index__"
EDITABLE_SCALES = {"linear", "log"}
_EPOCH = pd.Timestamp("1970-01-01")


# ------------------------------------------------------------------ helpers


def _finite_list(values: Any, limit: int) -> list[float] | None:
    if not isinstance(values, list) or len(values) > limit:
        return None
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        out.append(float(value))
    return out


def _referenced_columns(code: str, columns: list[str]) -> list[str]:
    """Columns named in the code (string literals or ``df.attr``), in order of appearance."""
    known = set(columns)
    found: list[str] = []
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return found
    nodes = sorted(
        (node for node in ast.walk(tree) if hasattr(node, "lineno")),
        key=lambda node: (node.lineno, getattr(node, "col_offset", 0)),
    )
    for node in nodes:
        name = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            name = node.value
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "df":
            name = node.attr
        if name in known and name not in found:
            found.append(name)
    return found


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _parse_dates(series: pd.Series) -> pd.Series | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.to_datetime(series, errors="coerce")
    except (TypeError, ValueError, OverflowError):
        return None


class _Column:
    """One candidate column prepared for matching on a given axis kind."""

    def __init__(self, name: str, kind: str, values: np.ndarray, editable: bool):
        self.name = name
        self.kind = kind  # "num" | "cat"
        self.values = values  # float array (num) or object array of str (cat)
        self.editable = editable
        if kind == "num":
            finite = values[np.isfinite(values)]
            self.sorted = np.unique(finite)
        else:
            self.lookup = set(values.tolist())

    def codes(self, points: list) -> list | None:
        """Canonical code for each point value, or None if any value is absent.

        Numeric codes are the column's own values, so they compare equal to
        the row values when rows are bucketed.
        """
        if self.kind == "cat":
            return list(points) if all(point in self.lookup for point in points) else None
        if self.sorted.size == 0:
            return None
        values = np.asarray(points, dtype=float)
        index = np.searchsorted(self.sorted, values)
        lower = self.sorted[np.clip(index - 1, 0, self.sorted.size - 1)]
        upper = self.sorted[np.clip(index, 0, self.sorted.size - 1)]
        nearest = np.where(np.abs(lower - values) <= np.abs(upper - values), lower, upper)
        if self.name.startswith("date:"):
            limit = DATE_TOLERANCE
        else:
            limit = REL_TOLERANCE * np.maximum(1.0, np.maximum(np.abs(values), np.abs(nearest)))
        if not bool(np.all(np.abs(nearest - values) <= limit)):
            return None
        return nearest.tolist()


class _Matcher:
    def __init__(self, frame: pd.DataFrame, code: str):
        self.frame = frame
        self.columns = [str(column) for column in frame.columns]
        referenced = _referenced_columns(code, self.columns)
        self.order = referenced + [column for column in self.columns if column not in referenced]
        self._prepared: dict[tuple[str, str], _Column | None] = {}
        # Rows already bound to a mark, per column pair: a second mark drawn
        # from the same columns prefers other rows (duplicate values).
        self._claimed: dict[tuple, set[int]] = defaultdict(set)

    # -- column preparation ---------------------------------------------------
    def _numeric(self, name: str) -> _Column | None:
        key = ("num", name)
        if key not in self._prepared:
            column = None
            if name == INDEX_COLUMN:
                column = _Column(INDEX_COLUMN, "num", np.arange(len(self.frame), dtype=float), editable=False)
            else:
                series = self.frame[name]
                if _is_numeric(series):
                    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
                    column = _Column(name, "num", values, editable=True)
            self._prepared[key] = column
        return self._prepared[key]

    def _date(self, name: str) -> _Column | None:
        key = ("date", name)
        if key not in self._prepared:
            column = None
            series = self.frame[name]
            if not _is_numeric(series) and not pd.api.types.is_bool_dtype(series):
                parsed = _parse_dates(series)
                if parsed is not None and getattr(parsed.dt, "tz", None) is not None:
                    parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
                if parsed is not None and parsed.notna().sum() >= max(1, int(0.9 * series.notna().sum())):
                    days = (parsed - _EPOCH) / pd.Timedelta(days=1)
                    values = days.to_numpy(dtype=float, na_value=np.nan)
                    column = _Column(f"date:{name}", "num", values, editable=False)
            self._prepared[key] = column
        return self._prepared[key]

    def _category(self, name: str) -> _Column | None:
        key = ("cat", name)
        if key not in self._prepared:
            # str() matches how seaborn and Matplotlib label categories
            # (1 -> "1", 1.5 -> "1.5"); missing values never match.
            labels = [
                None if value is None or (isinstance(value, float) and math.isnan(value)) else str(value)
                for value in self.frame[name].tolist()
            ]
            self._prepared[key] = _Column(name, "cat", np.array(labels, dtype=object), editable=False)
        return self._prepared[key]

    def candidates(self, axis: dict, values: list) -> list[tuple[_Column, list]]:
        """Columns that contain every value of one axis, with each point's code."""
        kind = axis.get("kind")
        out: list[tuple[_Column, list]] = []
        if kind == "cat":
            labels = _category_labels(axis.get("labels"), values)
            if labels is None:
                return out
            for name in self.order:
                column = self._category(name)
                codes = column.codes(labels) if column else None
                if codes is not None:
                    out.append((column, codes))
            return out
        if kind == "date":
            for name in self.order:
                column = self._date(name)
                codes = column.codes(values) if column else None
                if codes is not None:
                    out.append((column, codes))
            return out
        for name in [*self.order, INDEX_COLUMN]:
            column = self._numeric(name)
            codes = column.codes(values) if column else None
            if codes is not None:
                out.append((column, codes))
        # Numeric axes relabelled with set_xticklabels: also try the labels.
        if axis.get("ticks"):
            labels = _category_labels(axis.get("ticks"), values)
            if labels is not None:
                for name in self.order:
                    column = self._category(name)
                    codes = column.codes(labels) if column else None
                    if codes is not None:
                        out.append((column, codes))
        return out

    # -- row assignment ---------------------------------------------------------
    def assign(self, x_col: _Column, x_codes: list, y_col: _Column, y_codes: list) -> tuple[list[int], int] | None:
        """Bind each point to a distinct row with the same (x, y) values.

        Rows already claimed by another mark from the same columns are used only
        when nothing else fits (e.g. a line and a scatter of the same data).
        """
        x_values = pd.Series(x_col.values, copy=False)
        y_values = pd.Series(y_col.values, copy=False)
        mask = x_values.isin(set(x_codes)).to_numpy() & y_values.isin(set(y_codes)).to_numpy()
        buckets: dict[tuple, list[int]] = defaultdict(list)
        x_array, y_array = x_col.values, y_col.values
        for row in np.flatnonzero(mask).tolist():
            buckets[(x_array[row], y_array[row])].append(row)

        claimed = self._claimed[(x_col.kind, x_col.name, y_col.kind, y_col.name)]
        for avoid_claimed in (True, False):
            used: set[int] = set()
            rows: list[int] = []
            ambiguous = 0
            for key in zip(x_codes, y_codes):
                bucket = buckets.get(key, [])
                row = next((r for r in bucket if r not in used and not (avoid_claimed and r in claimed)), None)
                if row is None:
                    break
                if len(bucket) > 1:
                    ambiguous += 1
                used.add(row)
                rows.append(row)
            else:
                claimed.update(rows)
                return rows, ambiguous
        return None

    def match(self, x_axis: dict, x_values: list, y_axis: dict, y_values: list) -> dict | None:
        x_candidates = self.candidates(x_axis, x_values)
        if not x_candidates:
            return None
        y_candidates = self.candidates(y_axis, y_values)
        if not y_candidates:
            return None
        tried = 0
        for x_col, x_codes in x_candidates:
            for y_col, y_codes in y_candidates:
                if x_col.name == y_col.name and x_col.kind == y_col.kind:
                    continue
                if x_col.name == INDEX_COLUMN and y_col.name == INDEX_COLUMN:
                    continue
                tried += 1
                if tried > MAX_COLUMN_PAIRS:
                    return None
                assigned = self.assign(x_col, x_codes, y_col, y_codes)
                if assigned is not None:
                    rows, ambiguous = assigned
                    return {
                        "x_col": x_col,
                        "y_col": y_col,
                        "rows": rows,
                        "ambiguous": ambiguous,
                        "x_display": _display_values(x_col, x_codes),
                        "y_display": _display_values(y_col, y_codes),
                    }
        return None


def _category_labels(labels: Any, positions: list) -> list[str] | None:
    """Label of the category each position sits on (within CATEGORY_SNAP)."""
    if isinstance(labels, list) and labels and all(isinstance(item, (list, tuple)) and len(item) == 2 for item in labels):
        pairs = [(float(pos), str(text)) for pos, text in labels if isinstance(pos, (int, float)) and math.isfinite(pos)]
    else:
        return None
    if not pairs:
        return None
    pairs.sort()
    locations = np.array([pos for pos, _ in pairs])
    texts = [_clean_label(text) for _, text in pairs]
    out = []
    for value in positions:
        if not isinstance(value, (int, float)):
            return None
        index = int(np.argmin(np.abs(locations - value)))
        if abs(locations[index] - value) > CATEGORY_SNAP or not texts[index]:
            return None
        out.append(texts[index])
    return out


def _display_values(column: _Column, codes: list) -> list[str] | None:
    """Readable values for axes whose coordinates are not the data (categories, dates)."""
    if column.kind == "cat":
        return [str(code) for code in codes]
    if column.name.startswith("date:"):
        out = []
        for days in codes:
            stamp = _EPOCH + pd.Timedelta(days=float(days))
            out.append(stamp.date().isoformat() if stamp == stamp.normalize() else stamp.isoformat(sep=" "))
        return out
    return None


def _clean_label(text: str) -> str:
    # Matplotlib renders negative numbers with a Unicode minus sign.
    return text.replace("−", "-").strip()


def _axis_spec(column: Any, axis: dict, editable_axis: bool) -> dict:
    is_numeric_column = isinstance(column, _Column) and column.kind == "num" and column.editable
    spec = {
        "column": None if column is None or column.name == INDEX_COLUMN else column.name.removeprefix("date:"),
        "kind": axis.get("kind", "num"),
        "scale": axis.get("scale", "linear"),
        "editable": bool(editable_axis and is_numeric_column and axis.get("kind", "num") == "num" and axis.get("scale", "linear") in EDITABLE_SCALES),
    }
    if column is not None and column.name == INDEX_COLUMN:
        spec["index"] = True
    return spec


# ------------------------------------------------------------ matplotlib marks


def _clean_axis(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"kind": "num", "scale": "linear"}
    kind = raw.get("kind") if raw.get("kind") in {"num", "cat", "date"} else "num"
    scale = raw.get("scale") if isinstance(raw.get("scale"), str) else "linear"
    axis = {"kind": kind, "scale": scale[:16]}
    for key in ("labels", "ticks"):
        value = raw.get(key)
        if isinstance(value, list) and len(value) <= 2000:
            axis[key] = [
                [float(item[0]), str(item[1])[:200]]
                for item in value
                if isinstance(item, (list, tuple))
                and len(item) == 2
                and isinstance(item[0], (int, float))
                and not isinstance(item[0], bool)
                and math.isfinite(item[0])
            ]
    return axis


def _clean_box(raw: Any) -> list[float] | None:
    values = _finite_list(raw, 4)
    return values if values is not None and len(values) == 4 else None


def matplotlib_point_sets(meta: dict, frame: pd.DataFrame, code: str) -> dict:
    """Point sets for a Matplotlib render from its ``out.meta.json``."""
    raw_axes = meta.get("axes") if isinstance(meta.get("axes"), list) else []
    axes = []
    for raw in raw_axes[:50]:
        if not isinstance(raw, dict):
            axes.append(None)
            continue
        box = _clean_box(raw.get("box"))
        xlim = _finite_list(raw.get("xlim"), 2)
        ylim = _finite_list(raw.get("ylim"), 2)
        if box is None or xlim is None or ylim is None or len(xlim) != 2 or len(ylim) != 2:
            axes.append(None)
            continue
        axes.append({"box": box, "xlim": xlim, "ylim": ylim, "x": _clean_axis(raw.get("x")), "y": _clean_axis(raw.get("y"))})

    matcher = _Matcher(frame, code)
    sets: list[dict] = []
    unmatched = 0
    total = 0
    raw_sets = meta.get("sets") if isinstance(meta.get("sets"), list) else []
    for raw in raw_sets[:MAX_SETS]:
        if not isinstance(raw, dict) or not isinstance(raw.get("axes"), int) or not 0 <= raw["axes"] < len(axes):
            continue
        axis_index = raw["axes"]
        geometry = axes[axis_index]
        if geometry is None:
            continue
        kind = raw.get("kind")
        if kind == "bar":
            positions = _finite_list(raw.get("pos"), MAX_SET_POINTS)
            values = _finite_list(raw.get("value"), MAX_SET_POINTS)
            bases = _finite_list(raw.get("base"), MAX_SET_POINTS)
            if not positions or values is None or bases is None or not len(positions) == len(values) == len(bases):
                continue
            horizontal = raw.get("orientation") == "h"
            if horizontal:
                xs, ys, x_axis, y_axis = values, positions, geometry["x"], geometry["y"]
            else:
                xs, ys, x_axis, y_axis = positions, values, geometry["x"], geometry["y"]
        elif kind in {"line", "scatter"}:
            xs = _finite_list(raw.get("x"), MAX_SET_POINTS)
            ys = _finite_list(raw.get("y"), MAX_SET_POINTS)
            if not xs or ys is None or len(xs) != len(ys):
                continue
            x_axis, y_axis = geometry["x"], geometry["y"]
            bases = None
            horizontal = False
        else:
            continue
        if total + len(xs) > MAX_TOTAL_POINTS:
            break
        found = matcher.match(x_axis, xs, y_axis, ys)
        if found is None:
            unmatched += 1
            continue
        total += len(xs)
        label = str(raw.get("label") or "")[:120]
        point_set = {
            "id": f"m{len(sets)}",
            "axes": axis_index,
            "kind": kind,
            # Matplotlib names unlabelled artists "_child0", "_container1", ...
            "label": "" if label.startswith("_") else label,
            "x": _axis_spec(found["x_col"], x_axis, editable_axis=kind != "bar" or horizontal),
            "y": _axis_spec(found["y_col"], y_axis, editable_axis=kind != "bar" or not horizontal),
            "rows": found["rows"],
            "xs": xs,
            "ys": ys,
            "ambiguous": found["ambiguous"],
        }
        for key in ("x_display", "y_display"):
            if found[key] is not None:
                point_set[key] = found[key]
        if kind == "bar":
            point_set["orientation"] = "h" if horizontal else "v"
            point_set["bases"] = bases
        sets.append(point_set)
    return {"engine": "matplotlib", "axes": axes, "sets": sets, "unmatched": unmatched}


# ---------------------------------------------------------------- plotly marks

_BDATA_TYPES = {
    "f8": "<f8", "f4": "<f4", "i1": "<i1", "u1": "<u1", "i2": "<i2", "u2": "<u2", "i4": "<i4", "u4": "<u4", "i8": "<i8", "u8": "<u8",
}


def _plotly_array(value: Any, limit: int = MAX_SET_POINTS) -> list | None:
    """Decode a Plotly trace array (plain list or Plotly 6 typed ``bdata``)."""
    if isinstance(value, dict) and isinstance(value.get("bdata"), str) and value.get("dtype") in _BDATA_TYPES:
        raw = base64.b64decode(value["bdata"], validate=False)
        dtype = np.dtype(_BDATA_TYPES[value["dtype"]])
        if len(raw) % dtype.itemsize or len(raw) // dtype.itemsize > limit:
            return None
        return np.frombuffer(raw, dtype=dtype).astype(float).tolist()
    if isinstance(value, list) and len(value) <= limit:
        return value
    return None


def _plotly_axis_kind(layout_axis: dict, values: list) -> str:
    declared = layout_axis.get("type") if isinstance(layout_axis, dict) else None
    if declared in {"category", "multicategory"}:
        return "cat"
    if declared == "date":
        return "date"
    if declared in {"linear", "log"}:
        return "num"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "num"
    if all(isinstance(value, str) for value in values):
        parsed = _parse_dates(pd.Series(values))
        if parsed is not None and parsed.notna().all():
            return "date"
        return "cat"
    return "unknown"


def _plotly_values(kind: str, values: list) -> list | None:
    if kind == "num":
        out = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return None
            out.append(float(value))
        return out
    if kind == "cat":
        return [str(value) for value in values] if all(isinstance(value, (str, int, float)) for value in values) else None
    if kind == "date":
        parsed = _parse_dates(pd.Series(values))
        if parsed is None or parsed.isna().any():
            return None
        if getattr(parsed.dt, "tz", None) is not None:
            parsed = parsed.dt.tz_convert("UTC").dt.tz_localize(None)
        return ((parsed - _EPOCH) / pd.Timedelta(days=1)).astype(float).tolist()
    return None


def plotly_point_sets(figure: dict, frame: pd.DataFrame, code: str) -> dict:
    """Point sets for a Plotly figure (``out.plotly.json``)."""
    data = figure.get("data") if isinstance(figure.get("data"), list) else []
    layout = figure.get("layout") if isinstance(figure.get("layout"), dict) else {}
    matcher = _Matcher(frame, code)
    sets: list[dict] = []
    unmatched = 0
    total = 0
    for trace_index, trace in enumerate(data[:MAX_SETS]):
        if not isinstance(trace, dict) or trace.get("type", "scatter") not in {"scatter", "scattergl", "bar"}:
            continue
        if trace.get("visible") in (False, "legendonly"):
            continue
        is_bar = trace.get("type") == "bar"
        horizontal = is_bar and trace.get("orientation") == "h"
        raw_x = _plotly_array(trace.get("x"))
        raw_y = _plotly_array(trace.get("y"))
        if raw_x is None and raw_y is None:
            continue
        count = len(raw_y if raw_y is not None else raw_x)
        if count == 0 or count > MAX_SET_POINTS:
            continue
        if raw_x is None:
            raw_x = list(range(count))
        if raw_y is None:
            raw_y = list(range(count))
        if len(raw_x) != len(raw_y):
            continue
        if total + count > MAX_TOTAL_POINTS:
            break
        x_ref = str(trace.get("xaxis") or "x")
        y_ref = str(trace.get("yaxis") or "y")
        x_layout = layout.get("xaxis" + x_ref[1:], {})
        y_layout = layout.get("yaxis" + y_ref[1:], {})
        x_kind = _plotly_axis_kind(x_layout, raw_x)
        y_kind = _plotly_axis_kind(y_layout, raw_y)
        xs = _plotly_values(x_kind, raw_x)
        ys = _plotly_values(y_kind, raw_y)
        if xs is None or ys is None:
            unmatched += 1
            continue
        x_axis = {"kind": x_kind, "scale": "log" if isinstance(x_layout, dict) and x_layout.get("type") == "log" else "linear"}
        y_axis = {"kind": y_kind, "scale": "log" if isinstance(y_layout, dict) and y_layout.get("type") == "log" else "linear"}
        found = _match_plotly(matcher, x_axis, xs, y_axis, ys)
        if found is None:
            unmatched += 1
            continue
        total += count
        point_set = {
            "id": f"p{len(sets)}",
            "trace": trace_index,
            "xref": x_ref,
            "yref": y_ref,
            "kind": "bar" if is_bar else "scatter",
            "label": str(trace.get("name") or "")[:120],
            "x": _axis_spec(found["x_col"], x_axis, editable_axis=not is_bar or horizontal),
            "y": _axis_spec(found["y_col"], y_axis, editable_axis=not is_bar or not horizontal),
            "rows": found["rows"],
            "xs": raw_x if x_kind != "num" else xs,
            "ys": raw_y if y_kind != "num" else ys,
            "ambiguous": found["ambiguous"],
        }
        if is_bar:
            point_set["orientation"] = "h" if horizontal else "v"
            point_set["bases"] = [0.0] * count
        sets.append(point_set)
    return {"engine": "plotly", "axes": [], "sets": sets, "unmatched": unmatched}


def _match_plotly(matcher: _Matcher, x_axis: dict, xs: list, y_axis: dict, ys: list) -> dict | None:
    # Plotly category values are the labels themselves.
    def values_for(axis: dict, values: list) -> tuple[dict, list]:
        if axis["kind"] == "cat":
            return {**axis, "labels": [[float(i), label] for i, label in enumerate(dict.fromkeys(values))]}, [
                float(list(dict.fromkeys(values)).index(label)) for label in values
            ]
        return axis, values

    x_axis, x_values = values_for(x_axis, xs)
    y_axis, y_values = values_for(y_axis, ys)
    return matcher.match(x_axis, x_values, y_axis, y_values)


# ------------------------------------------------------------- revision entry


def point_sets_for_output(output_dir: Path, frame: pd.DataFrame, code: str) -> dict:
    """Editable point sets for a rendered revision's output directory."""
    plotly_path = output_dir / "out.plotly.json"
    meta_path = output_dir / "out.meta.json"
    try:
        if plotly_path.is_file():
            figure = json.loads(plotly_path.read_text(encoding="utf-8"))
            if isinstance(figure, dict):
                return plotly_point_sets(figure, frame, code)
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                return matplotlib_point_sets(meta, frame, code)
    except (OSError, ValueError, TypeError) as exc:
        return {"engine": "none", "axes": [], "sets": [], "unmatched": 0, "error": str(exc)[:300]}
    return {"engine": "none", "axes": [], "sets": [], "unmatched": 0}


# ----------------------------------------------------------------- cell edits


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return None if pd.isna(value) else str(value)


def apply_cell_edits(frame: pd.DataFrame, edits: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    """Return a copy of ``frame`` with ``edits`` applied and a log of changed cells.

    Each edit is ``{"row": int, "column": str, "value": number | str | None}``;
    ``None`` clears the cell (missing value).  Later edits of the same cell win.
    Cells whose value does not change are left out of the log.
    """
    if not isinstance(edits, list) or not edits:
        raise DataError("没有需要保存的修改")
    if len(edits) > MAX_EDITS:
        raise DataError(f"一次最多修改 {MAX_EDITS} 个单元格")
    result = frame.copy()
    rows = len(result)
    final: dict[tuple[int, str], Any] = {}
    for edit in edits:
        if not isinstance(edit, dict):
            raise DataError("修改项格式不正确")
        row = edit.get("row")
        column = edit.get("column")
        if isinstance(row, bool) or not isinstance(row, int) or not 0 <= row < rows:
            raise DataError(f"行号超出范围: {row}")
        if not isinstance(column, str) or column not in result.columns:
            raise DataError(f"列不存在: {column}")
        final[(row, column)] = edit.get("value")

    log: list[dict] = []
    for (row, column), value in final.items():
        series = result[column]
        old = series.iloc[row]
        if _is_numeric(series):
            if value is None or (isinstance(value, str) and not value.strip()):
                new_value = np.nan
            else:
                try:
                    new_value = float(value)
                except (TypeError, ValueError) as exc:
                    raise DataError(f"列 {column} 是数值列，第 {row + 1} 行的新值必须是数字") from exc
                if not math.isfinite(new_value):
                    raise DataError(f"列 {column} 第 {row + 1} 行的新值必须是有限数值")
            if pd.api.types.is_integer_dtype(series):
                if isinstance(new_value, float) and new_value.is_integer() and not math.isnan(new_value):
                    new_value = int(new_value)
                else:
                    result[column] = series.astype("float64")
            same = (pd.isna(old) and isinstance(new_value, float) and math.isnan(new_value)) or (
                not pd.isna(old) and not (isinstance(new_value, float) and math.isnan(new_value)) and float(old) == float(new_value)
            )
        else:
            if value is None:
                new_value = None
            elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
                new_value = value if isinstance(value, str) else (str(int(value)) if float(value).is_integer() else str(value))
            else:
                raise DataError(f"列 {column} 第 {row + 1} 行的新值类型不支持")
            if pd.api.types.is_bool_dtype(series) or not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
                result[column] = series.astype(object)
            same = (pd.isna(old) and new_value is None) or (not pd.isna(old) and str(old) == new_value)
        if same:
            continue
        result.iloc[row, result.columns.get_loc(column)] = new_value
        log.append({"row": row, "column": column, "old": _json_value(old), "new": _json_value(new_value)})
    if not log:
        raise DataError("修改后的值与原值相同，没有需要保存的修改")
    return result, log


def build_provenance(parent: dict, log: list[dict], note: str = "") -> dict:
    """Provenance for a corrected dataset: parent, root and the cumulative edit log."""
    previous = parent.get("provenance") if isinstance(parent.get("provenance"), dict) else {}
    step = int(previous.get("step", 0)) + 1
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    entries = list(previous.get("edits") or [])
    entries.extend({**entry, "step": step, "at": stamp, "note": note} for entry in log)
    truncated = bool(previous.get("truncated")) or len(entries) > MAX_PROVENANCE_EDITS
    return {
        "kind": "cell-edits",
        "parent_id": parent.get("id"),
        "parent_name": parent.get("name") or "",
        "root_id": previous.get("root_id") or parent.get("id"),
        "root_name": previous.get("root_name") or parent.get("name") or "",
        "step": step,
        "edit_count": len(entries),
        "edits": entries[-MAX_PROVENANCE_EDITS:],
        "truncated": truncated,
    }


def public_provenance(provenance: Any) -> dict | None:
    """Short provenance summary for dataset listings (no edit log)."""
    if not isinstance(provenance, dict) or not provenance:
        return None
    return {
        key: provenance.get(key)
        for key in ("kind", "parent_id", "parent_name", "root_id", "root_name", "step", "edit_count")
    }


def edits_csv(provenance: dict) -> str:
    """The edit log as CSV (1-based data row numbers) for project bundles."""
    frame = pd.DataFrame(
        [
            {
                "step": entry.get("step"),
                "data_row": int(entry.get("row", 0)) + 1,
                "column": entry.get("column"),
                "old_value": entry.get("old"),
                "new_value": entry.get("new"),
                "edited_at": entry.get("at"),
                "note": entry.get("note", ""),
            }
            for entry in provenance.get("edits") or []
        ],
        columns=["step", "data_row", "column", "old_value", "new_value", "edited_at", "note"],
    )
    return frame.to_csv(index=False)
