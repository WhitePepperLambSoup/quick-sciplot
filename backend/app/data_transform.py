"""Dataset preview, column values, declarative transforms and key-based joins.

Every operation is a fixed, validated pandas call; no user expression is ever
evaluated.
"""

import json
from pathlib import Path

import pandas as pd

from . import data_loader
from .data_loader import DataError

MAX_PREVIEW_ROWS = 500
MAX_COLUMN_VALUES = 1000
MAX_OPERATIONS = 20
FILTER_OPERATORS = {"==", "!=", ">", ">=", "<", "<=", "contains", "not_contains", "isnull", "notnull", "in"}
JOIN_TYPES = {"inner", "left", "right", "outer"}


def _records(frame: pd.DataFrame) -> list[dict]:
    """JSON-safe row records (NaN/inf become null, numpy scalars become Python)."""
    return data_loader._sanitize(json.loads(frame.to_json(orient="records", force_ascii=False, date_format="iso")))


def preview(path: str | Path, offset: int = 0, limit: int = 100) -> dict:
    frame = data_loader.load_dataframe(path)
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), MAX_PREVIEW_ROWS))
    window = frame.iloc[offset : offset + limit]
    return {
        "columns": [str(column) for column in frame.columns],
        "dtypes": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
        "rows": _records(window),
        "offset": offset,
        "total_rows": int(frame.shape[0]),
    }


def column_values(path: str | Path, column: str, limit: int = MAX_COLUMN_VALUES) -> dict:
    """Distinct values of one column, most frequent first."""
    frame = data_loader.load_dataframe(path)
    _require_columns(frame, [column])
    counts = frame[column].dropna().astype(str).value_counts()
    limit = max(1, min(int(limit), MAX_COLUMN_VALUES))
    return {
        "column": column,
        "values": [{"value": value, "count": int(count)} for value, count in counts.head(limit).items()],
        "total_unique": int(counts.shape[0]),
        "truncated": int(counts.shape[0]) > limit,
    }


def _require_columns(frame: pd.DataFrame, columns: list) -> None:
    missing = [str(column) for column in columns if column not in frame.columns]
    if missing:
        raise DataError(f"列不存在: {', '.join(missing)}")


def _string_list(value, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DataError(f"{name} 必须是列名数组")
    return value


def _coerce_like(series: pd.Series, value):
    """Interpret a filter value with the column's type (numbers stay numbers)."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise DataError(f"数值列的筛选值必须是数字: {value!r}") from exc
    return str(value)


def _filter(frame: pd.DataFrame, op: dict) -> pd.DataFrame:
    column = op.get("column")
    operator = op.get("operator")
    _require_columns(frame, [column])
    if operator not in FILTER_OPERATORS:
        raise DataError(f"不支持的筛选条件: {operator}")
    series = frame[column]
    if operator == "isnull":
        return frame[series.isna()]
    if operator == "notnull":
        return frame[series.notna()]
    if operator in {"contains", "not_contains"}:
        mask = series.astype(str).str.contains(str(op.get("value", "")), regex=False, na=False)
        return frame[mask if operator == "contains" else ~mask]
    if operator == "in":
        values = op.get("value")
        if not isinstance(values, list):
            raise DataError("in 条件的值必须是数组")
        return frame[series.astype(str).isin([str(item) for item in values])]
    value = _coerce_like(series, op.get("value"))
    compare = series if isinstance(value, float) else series.astype(str)
    mask = {
        "==": compare == value,
        "!=": compare != value,
        ">": compare > value,
        ">=": compare >= value,
        "<": compare < value,
        "<=": compare <= value,
    }[operator]
    return frame[mask.fillna(False)]


def _melt(frame: pd.DataFrame, op: dict) -> pd.DataFrame:
    id_vars = _string_list(op.get("id_vars", []), "id_vars")
    value_vars = op.get("value_vars")
    if value_vars is not None:
        value_vars = _string_list(value_vars, "value_vars")
    _require_columns(frame, id_vars + (value_vars or []))
    var_name = str(op.get("var_name") or "variable")
    value_name = str(op.get("value_name") or "value")
    if var_name == value_name or var_name in id_vars or value_name in id_vars:
        raise DataError("宽表转长表的新列名不能与已有列或彼此重复")
    return frame.melt(id_vars=id_vars, value_vars=value_vars, var_name=var_name, value_name=value_name)


def _apply(frame: pd.DataFrame, op: dict) -> pd.DataFrame:
    if not isinstance(op, dict):
        raise DataError("每个操作必须是对象")
    kind = op.get("op")
    if kind == "filter":
        return _filter(frame, op)
    if kind == "melt":
        return _melt(frame, op)
    if kind == "select":
        columns = _string_list(op.get("columns"), "columns")
        _require_columns(frame, columns)
        if not columns:
            raise DataError("至少保留一列")
        return frame[columns]
    if kind == "rename":
        mapping = op.get("mapping")
        if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in mapping.items()):
            raise DataError("rename 需要 {旧列名: 新列名} 映射")
        _require_columns(frame, list(mapping))
        renamed = frame.rename(columns={k: v.strip() for k, v in mapping.items()})
        if renamed.columns.duplicated().any():
            raise DataError("重命名后出现重复列名")
        return renamed
    if kind == "dropna":
        columns = op.get("columns")
        if columns is not None:
            _require_columns(frame, _string_list(columns, "columns"))
        return frame.dropna(subset=columns)
    if kind == "sort":
        column = op.get("column")
        _require_columns(frame, [column])
        return frame.sort_values(column, ascending=bool(op.get("ascending", True)), kind="stable")
    raise DataError(f"不支持的数据操作: {kind}")


def transform(path: str | Path, operations: list) -> pd.DataFrame:
    if not isinstance(operations, list) or not operations:
        raise DataError("至少需要一个数据操作")
    if len(operations) > MAX_OPERATIONS:
        raise DataError(f"一次最多 {MAX_OPERATIONS} 个数据操作")
    frame = data_loader.load_dataframe(path)
    for op in operations:
        frame = _apply(frame, op)
    if frame.shape[0] == 0:
        raise DataError("处理后没有剩余数据行")
    return frame.reset_index(drop=True)


def join(
    left_path: str | Path,
    right_path: str | Path,
    left_on: list[str],
    right_on: list[str],
    how: str = "inner",
) -> pd.DataFrame:
    left_on = _string_list(left_on, "left_on")
    right_on = _string_list(right_on, "right_on")
    if not left_on or len(left_on) != len(right_on):
        raise DataError("左右连接键数量必须相同且至少一个")
    if how not in JOIN_TYPES:
        raise DataError(f"连接方式只能是 {sorted(JOIN_TYPES)}")
    left = data_loader.load_dataframe(left_path)
    right = data_loader.load_dataframe(right_path)
    _require_columns(left, left_on)
    _require_columns(right, right_on)

    # Joining on keys as text keeps 1 and "1" equal across CSV type inference.
    left_keys = left[left_on].astype(str)
    right_keys = right[right_on].astype(str)
    left_counts = left_keys.value_counts()
    right_counts = right_keys.value_counts()
    left_counts.index = left_counts.index.to_flat_index()
    right_counts.index = right_counts.index.to_flat_index()
    shared = left_counts.index.intersection(right_counts.index)
    matched = int((left_counts[shared] * right_counts[shared]).sum()) if len(shared) else 0
    estimate = matched
    if how in {"left", "outer"}:
        estimate += int(left_counts.drop(shared).sum())
    if how in {"right", "outer"}:
        estimate += int(right_counts.drop(shared).sum())
    if estimate > data_loader.MAX_ROWS_FOR_COMBINE:
        raise DataError(f"连接结果约 {estimate:,} 行，超过 {data_loader.MAX_ROWS_FOR_COMBINE:,} 行限制；请检查连接键是否唯一")

    left = left.copy()
    right = right.copy()
    key_names = [f"__key_{index}" for index in range(len(left_on))]
    for name, column in zip(key_names, left_on):
        left[name] = left[column].astype(str)
    for name, column in zip(key_names, right_on):
        right[name] = right[column].astype(str)
    merged = left.merge(right, on=key_names, how=how, suffixes=("", "_right"))
    merged = merged.drop(columns=key_names)
    if merged.shape[0] == 0:
        raise DataError("连接结果为空：两个数据集没有匹配的键")
    return merged.reset_index(drop=True)
