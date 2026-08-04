"""数据导入与摘要：上传文件 -> 归一化 CSV -> 统计摘要（供 LLM 理解数据）。"""

import json
import re
import uuid
from pathlib import Path

import pandas as pd

ALLOWED_EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json"}
MAX_ROWS_FOR_STATS = 200_000


class DataError(Exception):
    pass


def _read_frame(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext == ".tsv":
        return pd.read_csv(path, sep="\t")
    if ext == ".txt":
        try:
            return pd.read_csv(path, sep="\t")
        except Exception:
            return pd.read_csv(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if ext == ".json":
        return pd.read_json(path)
    raise DataError(f"不支持的文件类型: {ext}")


def _col_summary(col: pd.Series, name: str) -> dict:
    non_null = col.dropna()
    item: dict = {"name": name, "dtype": str(col.dtype), "nulls": int(col.isna().sum()), "n_unique": int(col.nunique())}
    if pd.api.types.is_numeric_dtype(col):
        if len(non_null):
            item["min"] = float(non_null.min())
            item["max"] = float(non_null.max())
            item["mean"] = round(float(non_null.mean()), 4)
            item["median"] = round(float(non_null.median()), 4)
            item["std"] = round(float(non_null.std()), 4)
    else:
        counts = non_null.astype(str).value_counts().head(5)
        item["top_values"] = [{"value": v, "count": int(c)} for v, c in counts.items()]
    return item


def build_summary(df: pd.DataFrame) -> dict:
    df = df.replace({float("nan"): None})
    return {
        "shape": {"rows": int(df.shape[0]), "cols": int(df.shape[1])},
        "columns": [_col_summary(df[c], c) for c in df.columns],
        "head": json.loads(df.head(10).to_json(orient="records", force_ascii=False)),
    }


def import_dataset(data_dir: Path, filename: str, content: bytes) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise DataError(f"不支持的文件类型: {ext}，支持 {sorted(ALLOWED_EXTS)}")

    raw_path = data_dir / f"{uuid.uuid4().hex}{ext}"
    raw_path.write_bytes(content)

    try:
        df = _read_frame(raw_path)
    except Exception as exc:
        raw_path.unlink(missing_ok=True)
        raise DataError(f"文件解析失败: {exc}") from exc

    if df.shape[0] == 0:
        raw_path.unlink(missing_ok=True)
        raise DataError("文件为空")

    if df.shape[0] > MAX_ROWS_FOR_STATS:
        df = df.sample(MAX_ROWS_FOR_STATS, random_state=42)

    dataset_id = uuid.uuid4().hex
    csv_path = data_dir / f"{dataset_id}.csv"
    df.to_csv(csv_path, index=False)
    raw_path.unlink(missing_ok=True)

    summary = build_summary(df)
    summary["columns"] = _sanitize(summary["columns"])
    return {"id": dataset_id, "path": str(csv_path), "summary": summary}


def _sanitize(obj):
    """确保 JSON 可序列化（处理 numpy 标量等）。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "item"):
        return _sanitize(obj.item())
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def summarize_csv(data_dir: Path, csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    if df.shape[0] > MAX_ROWS_FOR_STATS:
        df = df.sample(MAX_ROWS_FOR_STATS, random_state=42)
    summary = build_summary(df)
    summary["columns"] = _sanitize(summary["columns"])
    return summary
