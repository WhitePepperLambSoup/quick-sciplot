"""数据导入与摘要：上传文件 -> 归一化 CSV -> 统计摘要（供 LLM 理解数据）。"""

import json
import math
import os
import re
import tempfile
import threading
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from .config import settings

ALLOWED_EXTS = {".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json"}
MAX_ROWS_FOR_STATS = 200_000
MAX_ROWS_FOR_COMBINE = 1_000_000
MAX_IMPORT_ROWS = 1_000_000
MAX_IMPORT_COLUMNS = 200
MAX_IMPORT_CELLS = 5_000_000
JSON_READ_CHUNK_CHARS = 64 * 1024


class DataError(Exception):
    pass


class DataBusyError(DataError):
    """解析资源达到并发上限，调用方应让客户端稍后重试。"""


_PARSE_CONDITION = threading.Condition()
_PARSE_ACTIVE = 0


@contextmanager
def _parse_slot():
    global _PARSE_ACTIVE
    limit = max(1, int(settings.max_parse_concurrency))
    with _PARSE_CONDITION:
        if _PARSE_ACTIVE >= limit:
            raise DataBusyError("解析资源繁忙，请稍后重试")
        _PARSE_ACTIVE += 1
    try:
        yield
    finally:
        with _PARSE_CONDITION:
            _PARSE_ACTIVE -= 1
            _PARSE_CONDITION.notify()


def _zip_limits(path: Path) -> tuple[int, int]:
    """Return ZIP member count and declared expanded size without extracting."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            return len(infos), sum(max(0, int(info.file_size)) for info in infos)
    except zipfile.BadZipFile:
        return 0, 0


def validate_source_path(path: Path) -> None:
    """Reject oversized or suspiciously expandable input before pandas parses it."""
    try:
        stat = path.stat()
    except OSError as exc:
        raise DataError(f"数据文件不可读: {exc}") from exc
    if not path.is_file():
        raise DataError("数据文件不是普通文件")
    if stat.st_size > settings.max_import_bytes:
        raise DataError(f"源文件超过 {settings.max_import_bytes // (1024 * 1024)}MB 限制")
    if path.suffix.lower() == ".json" and stat.st_size > settings.max_json_bytes:
        raise DataError(f"JSON 文件超过 {settings.max_json_bytes // (1024 * 1024)}MB 限制")

    if path.suffix.lower() == ".xlsx":
        members, expanded_bytes = _zip_limits(path)
        if members > settings.max_archive_members:
            raise DataError(f"Excel 压缩包文件数量超过 {settings.max_archive_members} 个限制")
        if expanded_bytes > settings.max_archive_expanded_bytes:
            raise DataError(
                f"Excel 压缩包展开大小超过 {settings.max_archive_expanded_bytes // (1024 * 1024)}MB 限制"
            )


def _read_csv_with_fallback(path: Path, sep: str = ",") -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "latin1"]
    last_err: Exception | None = None
    for enc in encodings:
        try:
            return pd.read_csv(path, sep=sep, encoding=enc, nrows=MAX_IMPORT_ROWS + 1)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_err = exc
            continue
    raise DataError(f"无法以常见编码解析 CSV 文件: {last_err}")


def _read_delimited_text(path: Path) -> pd.DataFrame:
    """Read a .txt table whose delimiter is unknown (tab, comma or semicolon).

    Parsing a comma-separated file with ``sep="\\t"`` does not raise; it yields a
    single column, so the delimiter has to be chosen by the resulting width.
    """
    best: pd.DataFrame | None = None
    last_err: Exception | None = None
    for sep in ("\t", ",", ";"):
        try:
            candidate = _read_csv_with_fallback(path, sep=sep)
        except Exception as exc:  # 换一个分隔符继续尝试
            last_err = exc
            continue
        if candidate.shape[1] > 1:
            return candidate
        if best is None:
            best = candidate
    if best is None:
        raise DataError(f"无法解析文本表格: {last_err}")
    return best


def _read_excel_smart(path: Path) -> pd.DataFrame:
    try:
        with pd.ExcelFile(path) as excel:
            if len(excel.sheet_names) > settings.max_excel_sheets:
                raise DataError(f"Excel 工作表数量超过 {settings.max_excel_sheets} 个限制")
            for sheet in excel.sheet_names:
                df = excel.parse(sheet, nrows=MAX_IMPORT_ROWS + 1)
                if not df.empty and df.shape[1] > 0:
                    return df
            return pd.read_excel(path, nrows=MAX_IMPORT_ROWS + 1)
    except Exception as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"读取 Excel 文件失败: {exc}") from exc


def _validate_json_nesting(text: str) -> None:
    """Reject deeply nested JSON before the standard decoder recurses."""
    _scan_json_nesting((text,))


def _scan_json_nesting(chunks) -> None:
    depth = 0
    in_string = False
    escaped = False
    for text in chunks:
        for char in text:
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char in "[{":
                depth += 1
                if depth > max(1, int(settings.max_json_nesting)):
                    raise DataError(f"JSON 嵌套深度超过 {settings.max_json_nesting} 层限制")
            elif char in "]}":
                depth -= 1
                if depth < 0:
                    raise DataError("JSON 结构无效")
    if in_string or depth != 0:
        raise DataError("JSON 结构无效")


def _validate_json_nesting_file(path: Path) -> None:
    with path.open("r", encoding="utf-8-sig") as handle:
        chunks = iter(lambda: handle.read(JSON_READ_CHUNK_CHARS), "")
        _scan_json_nesting(chunks)


def _json_dataframe_from_document(payload: object) -> pd.DataFrame:
    if isinstance(payload, list):
        return pd.DataFrame.from_records(payload)
    if isinstance(payload, dict):
        for key in ("records", "data", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return pd.DataFrame.from_records(candidate)
        try:
            return pd.DataFrame(payload)
        except (TypeError, ValueError):
            return pd.json_normalize(payload)
    raise DataError("JSON 顶层结构必须是数组或对象")


def _read_json_array(path: Path) -> pd.DataFrame:
    """Decode a top-level JSON array incrementally and enforce row budgets early."""
    decoder = json.JSONDecoder()
    records: list[object] = []
    column_names: set[str] = set()
    buffer = ""
    eof = False

    with path.open("r", encoding="utf-8-sig") as handle:
        while not buffer and not eof:
            chunk = handle.read(JSON_READ_CHUNK_CHARS)
            if chunk:
                buffer += chunk
            else:
                eof = True
        buffer = buffer.lstrip()
        if not buffer.startswith("["):
            raise DataError("JSON 顶层数组解析失败")
        buffer = buffer[1:]

        while True:
            buffer = buffer.lstrip()
            while not buffer and not eof:
                chunk = handle.read(JSON_READ_CHUNK_CHARS)
                if chunk:
                    buffer += chunk
                else:
                    eof = True
                buffer = buffer.lstrip()
            if buffer.startswith("]"):
                buffer = buffer[1:]
                break
            if not buffer:
                raise DataError("JSON 数组缺少结束括号")

            while True:
                try:
                    value, consumed = decoder.raw_decode(buffer)
                    break
                except json.JSONDecodeError as exc:
                    if eof:
                        raise DataError(f"JSON 解析失败: {exc.msg}") from exc
                    chunk = handle.read(JSON_READ_CHUNK_CHARS)
                    if chunk:
                        buffer += chunk
                    else:
                        eof = True
                except RecursionError as exc:
                    raise DataError("JSON 嵌套深度超过解析器限制") from exc

            records.append(value)
            if len(records) > MAX_IMPORT_ROWS:
                raise DataError(f"数据行数超过 {MAX_IMPORT_ROWS:,} 行限制")
            if isinstance(value, dict):
                column_names.update(str(key) for key in value)
                if len(column_names) > MAX_IMPORT_COLUMNS:
                    raise DataError(f"数据列数超过 {MAX_IMPORT_COLUMNS} 列限制")
            elif isinstance(value, (list, tuple)) and len(value) > MAX_IMPORT_COLUMNS:
                raise DataError(f"数据列数超过 {MAX_IMPORT_COLUMNS} 列限制")
            estimated_columns = max(1, len(column_names))
            if len(records) * estimated_columns > MAX_IMPORT_CELLS:
                raise DataError(f"数据单元格数量超过 {MAX_IMPORT_CELLS:,} 个限制")

            buffer = buffer[consumed:].lstrip()
            if buffer.startswith(","):
                buffer = buffer[1:]
                continue
            if buffer.startswith("]"):
                buffer = buffer[1:]
                break
            while not buffer and not eof:
                chunk = handle.read(JSON_READ_CHUNK_CHARS)
                if chunk:
                    buffer += chunk
                else:
                    eof = True
                buffer = buffer.lstrip()
            if buffer.startswith(","):
                buffer = buffer[1:]
                continue
            if buffer.startswith("]"):
                buffer = buffer[1:]
                break
            raise DataError("JSON 数组元素之间缺少逗号")

        while True:
            if buffer.strip():
                raise DataError("JSON 文档包含额外内容")
            if eof:
                break
            chunk = handle.read(JSON_READ_CHUNK_CHARS)
            if chunk:
                buffer += chunk
            else:
                eof = True

    return pd.DataFrame.from_records(records)


def _read_json_safely(path: Path) -> pd.DataFrame:
    size = path.stat().st_size
    if size > settings.max_json_bytes:
        raise DataError(f"JSON 文件超过 {settings.max_json_bytes // (1024 * 1024)}MB 限制")

    with path.open("r", encoding="utf-8-sig") as handle:
        prefix = handle.read(JSON_READ_CHUNK_CHARS).lstrip()
    if prefix.startswith("["):
        _validate_json_nesting_file(path)
        return _read_json_array(path)

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            text = handle.read(settings.max_json_bytes + 1)
        if len(text.encode("utf-8")) > settings.max_json_bytes:
            raise DataError(f"JSON 文件超过 {settings.max_json_bytes // (1024 * 1024)}MB 限制")
        _validate_json_nesting(text)
        payload = json.loads(text)
        return _json_dataframe_from_document(payload)
    except DataError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DataError(f"JSON 文件解析失败: {exc}") from exc


def _read_frame(path: Path) -> pd.DataFrame:
    validate_source_path(path)
    with _parse_slot():
        ext = path.suffix.lower()
        df: pd.DataFrame
        if ext == ".csv":
            df = _read_csv_with_fallback(path, sep=",")
        elif ext == ".tsv":
            df = _read_csv_with_fallback(path, sep="\t")
        elif ext == ".txt":
            df = _read_delimited_text(path)
        elif ext in (".xlsx", ".xls"):
            df = _read_excel_smart(path)
        elif ext == ".json":
            df = _read_json_safely(path)
        else:
            raise DataError(f"不支持的文件类型: {ext}")

        # 清理列名中的前后空格和换行符，防止 LLM 生成代码因微小空白引发 KeyError
        df.columns = [str(c).strip() for c in df.columns]
        _validate_frame_size(df)
        return df


def _validate_frame_size(df: pd.DataFrame) -> None:
    rows, columns = df.shape
    if rows > MAX_IMPORT_ROWS:
        raise DataError(f"数据行数超过 {MAX_IMPORT_ROWS:,} 行限制")
    if columns > MAX_IMPORT_COLUMNS:
        raise DataError(f"数据列数超过 {MAX_IMPORT_COLUMNS} 列限制")
    if rows * columns > MAX_IMPORT_CELLS:
        raise DataError(f"数据单元格数量超过 {MAX_IMPORT_CELLS:,} 个限制")


def load_dataframe(path: Path | str) -> pd.DataFrame:
    """安全读取数据文件（自动处理编码、分隔符及列名空格）。"""
    return _read_frame(Path(path))


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
    rows_count, cols_count = int(df.shape[0]), int(df.shape[1])
    sample_df = df
    if rows_count > MAX_ROWS_FOR_STATS:
        # 保留前部连续行，避免打乱时序顺序
        sample_df = df.iloc[:MAX_ROWS_FOR_STATS]
    # 不要用 replace({nan: None}) 清理：它会把含缺失值的数值列转成 object，
    # 导致这些列失去 min/max/mean 并被当成分类列发给 LLM。
    # to_json 本身会把 NaN 输出为 null，_sanitize 会处理剩余的非有限数。
    summary = {
        "shape": {"rows": rows_count, "cols": cols_count},
        "columns": [_col_summary(sample_df[c], c) for c in df.columns],
        "head": json.loads(df.head(10).to_json(orient="records", force_ascii=False)),
    }
    return _sanitize(summary)


def import_dataset_file(data_dir: Path, filename: str, source_path: Path) -> dict:
    """解析已落盘的源文件，并生成内部规范化 CSV。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise DataError(f"不支持的文件类型: {ext}，支持 {sorted(ALLOWED_EXTS)}")
    try:
        df = _read_frame(source_path)
    except DataBusyError:
        raise
    except DataError:
        raise
    except Exception as exc:
        raise DataError(f"文件解析失败: {exc}") from exc

    if df.shape[0] == 0:
        raise DataError("文件为空")

    return create_dataset(data_dir, df, filename)


def import_dataset(data_dir: Path, filename: str, content: bytes) -> dict:
    """兼容小型内部调用；HTTP 上传路径使用 import_dataset_file 避免内存累积。"""
    ext = Path(filename).suffix.lower()
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".import-", suffix=ext, dir=data_dir, delete=False) as handle:
        raw_path = Path(handle.name)
        handle.write(content)
    try:
        return import_dataset_file(data_dir, filename, raw_path)
    finally:
        raw_path.unlink(missing_ok=True)


def create_dataset(data_dir: Path, df: pd.DataFrame, name: str) -> dict:
    if df.shape[0] == 0:
        raise DataError("文件为空")
    _validate_frame_size(df)
    data_dir.mkdir(parents=True, exist_ok=True)
    dataset_id = uuid.uuid4().hex
    csv_path = data_dir / f"{dataset_id}.csv"
    summary = build_summary(df)
    summary["columns"] = _sanitize(summary["columns"])

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{dataset_id}-",
            suffix=".csv",
            dir=data_dir,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            df.to_csv(handle, index=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, csv_path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise DataError(f"保存数据集失败: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {"id": dataset_id, "name": name, "path": str(csv_path), "summary": summary}


def combine_datasets(data_dir: Path, datasets: list[dict]) -> dict:
    if len(datasets) < 2:
        raise DataError("至少选择两个文件进行合并")
    frames = []
    for dataset in datasets:
        path = Path(dataset["path"])
        if not path.is_file():
            raise DataError(f"数据文件不存在: {dataset.get('name', path.name)}")
        frame = _read_frame(path)
        source_name = dataset.get("name") or path.stem
        if "source_file" in frame.columns:
            # 已合并过的数据集：保留原有来源，只给缺失值补上当前数据集名称。
            frame["source_file"] = frame["source_file"].where(frame["source_file"].notna(), source_name)
        else:
            frame.insert(0, "source_file", source_name)
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True, sort=False)
    if combined.shape[0] > MAX_ROWS_FOR_COMBINE:
        raise DataError(f"合并后超过 {MAX_ROWS_FOR_COMBINE:,} 行限制，请先筛选数据")
    return create_dataset(data_dir, combined, f"合并数据（{len(datasets)} 个文件）")


def _sanitize(obj):
    """确保 JSON 可序列化（处理 numpy 标量等）。"""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if hasattr(obj, "item"):
        return _sanitize(obj.item())
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


def summarize_csv(data_dir: Path, csv_path: Path) -> dict:
    df = _read_frame(csv_path)
    if df.shape[0] > MAX_ROWS_FOR_STATS:
        df = df.sample(MAX_ROWS_FOR_STATS, random_state=42)
    summary = build_summary(df)
    summary["columns"] = _sanitize(summary["columns"])
    return summary
