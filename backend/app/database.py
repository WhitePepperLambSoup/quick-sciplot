"""SQLite 持久化：数据集元信息与绘图版本历史。"""

import json
import math
import shutil
import sqlite3
import threading
import uuid
from pathlib import Path

from .config import settings

# Output directories that exist on disk before their revision row does (a plot is
# still rendering).  Orphan cleanup must not treat them as abandoned.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_OUTPUTS: set[Path] = set()


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _db_path() -> Path:
    return settings.data_dir / "history.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def safe_dataset_path(data_dir: Path, raw_path: str | Path) -> Path | None:
    """Return a canonical dataset path only for a regular CSV below data_dir."""
    try:
        raw_candidate = Path(raw_path)
        if raw_candidate.is_symlink():
            return None
        data_root = data_dir.resolve()
        candidate = raw_candidate.resolve()
        if candidate.parent != data_root or candidate.suffix.lower() != ".csv":
            return None
        if candidate.is_symlink() or not candidate.is_file():
            return None
        return candidate
    except (OSError, TypeError, ValueError):
        return None


def init_db() -> None:
    settings.ensure_dirs()
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                path TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS revisions (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                code TEXT NOT NULL,
                preset TEXT NOT NULL DEFAULT 'default',
                operation TEXT NOT NULL DEFAULT 'generate',
                output_dir TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                stderr TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_revisions_dataset ON revisions(dataset_id);
            """
        )
        # Columns added after 0.2.0; ALTER keeps existing user history.
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(revisions)").fetchall()}
        if "label" not in existing:
            conn.execute("ALTER TABLE revisions ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        if "starred" not in existing:
            conn.execute("ALTER TABLE revisions ADD COLUMN starred INTEGER NOT NULL DEFAULT 0")
        dataset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)").fetchall()}
        if "provenance_json" not in dataset_columns:
            # Where a corrected dataset came from and every cell edit (0.3.0).
            conn.execute("ALTER TABLE datasets ADD COLUMN provenance_json TEXT NOT NULL DEFAULT ''")


def _provenance(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    return _json_safe(value) if isinstance(value, dict) else None


MAX_REVISION_LABEL = 80


def update_revision(revision_id: str, *, label: str | None = None, starred: bool | None = None) -> dict | None:
    """Rename or (un)star a revision; starred revisions are exempt from pruning."""
    assignments: list[str] = []
    values: list[object] = []
    if label is not None:
        clean = " ".join(str(label).split())[:MAX_REVISION_LABEL]
        assignments.append("label = ?")
        values.append(clean)
    if starred is not None:
        assignments.append("starred = ?")
        values.append(int(bool(starred)))
    if assignments:
        with _connect() as conn:
            cursor = conn.execute(
                f"UPDATE revisions SET {', '.join(assignments)} WHERE id = ?",
                [*values, revision_id],
            )
            if cursor.rowcount == 0:
                return None
    revision = get_revision(revision_id)
    return public_revision(revision) if revision else None


def save_dataset(dataset: dict) -> None:
    path = safe_dataset_path(settings.data_dir, dataset.get("path", ""))
    if path is None:
        raise ValueError("数据集路径必须是 data_dir 下的普通 CSV 文件")
    provenance = dataset.get("provenance")
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO datasets(id, name, path, summary_json, provenance_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dataset["id"],
                dataset.get("name", ""),
                str(path),
                json.dumps(dataset.get("summary", {}), ensure_ascii=False),
                json.dumps(_json_safe(provenance), ensure_ascii=False) if isinstance(provenance, dict) else "",
            ),
        )


def get_dataset(dataset_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, name, path, summary_json, provenance_json FROM datasets WHERE id = ?", (dataset_id,)
        ).fetchone()
    if row is None:
        return None
    path = safe_dataset_path(settings.data_dir, row["path"])
    if path is None:
        return None
    dataset = {
        "id": row["id"],
        "name": row["name"],
        "path": str(path),
        "summary": _json_safe(json.loads(row["summary_json"])),
    }
    provenance = _provenance(row["provenance_json"])
    if provenance:
        dataset["provenance"] = provenance
    return dataset


def list_datasets(*, include_path: bool = False) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, name, path, summary_json, provenance_json FROM datasets ORDER BY created_at DESC"
        ).fetchall()
    datasets = []
    for row in rows:
        path = safe_dataset_path(settings.data_dir, row["path"])
        if path is None:
            continue
        try:
            item = {
                "id": row["id"],
                "name": row["name"] or path.stem,
                "summary": _json_safe(json.loads(row["summary_json"])),
            }
            if include_path:
                item["path"] = str(path)
            provenance = _provenance(row["provenance_json"])
            if provenance:
                item["provenance"] = provenance
            datasets.append(item)
        except Exception:
            continue
    return datasets


def delete_dataset(dataset_id: str) -> bool:
    output_dirs: list[Path] = []
    with _connect() as conn:
        row = conn.execute("SELECT path FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if row is None:
            return False
        path = safe_dataset_path(settings.data_dir, row["path"])

        # 查找该数据集关联的所有版本产物输出目录
        rev_rows = conn.execute("SELECT output_dir FROM revisions WHERE dataset_id = ?", (dataset_id,)).fetchall()
        for r in rev_rows:
            if r["output_dir"]:
                output_dir = _safe_output_dir(settings.data_dir, r["output_dir"])
                if output_dir is not None:
                    output_dirs.append(output_dir)

        conn.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))

    # 清理源数据文件
    if path is not None and path.exists():
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    # 清理所有历史绘图产物目录，释放磁盘空间
    for out_dir in output_dirs:
        if out_dir.exists() and out_dir.is_dir():
            try:
                shutil.rmtree(out_dir, ignore_errors=True)
            except Exception:
                pass
    return True


def mark_output_inflight(output_dir: Path) -> None:
    """Protect an output directory from orphan cleanup until its revision is saved.

    Call this *before* the directory is created.
    """
    with _INFLIGHT_LOCK:
        _INFLIGHT_OUTPUTS.add(Path(output_dir).resolve())


def release_output_inflight(output_dir: Path) -> None:
    with _INFLIGHT_LOCK:
        _INFLIGHT_OUTPUTS.discard(Path(output_dir).resolve())


def cleanup_orphaned_outputs(data_dir: Path | None = None) -> int:
    """清理 outputs 目录下未被任何有效 revision 引用的孤立历史产物目录。"""
    if data_dir is None:
        data_dir = settings.data_dir
    outputs_root = (data_dir / "outputs").resolve()
    if not outputs_root.exists() or not outputs_root.is_dir():
        return 0

    # The lock is held for the whole sweep so a plot that starts concurrently
    # either registers first (and is skipped) or creates its directory after the
    # sweep has finished.  Otherwise a second request could delete the output
    # directory of a render that is still running.
    with _INFLIGHT_LOCK:
        with _connect() as conn:
            rows = conn.execute("SELECT output_dir FROM revisions").fetchall()
            active_dirs = {
                output_dir
                for r in rows
                if r["output_dir"]
                for output_dir in [_safe_output_dir(data_dir, r["output_dir"])]
                if output_dir is not None
            }
        protected = active_dirs | _INFLIGHT_OUTPUTS

        cleaned_count = 0
        for child in outputs_root.iterdir():
            if child.is_dir() and child.resolve() not in protected:
                try:
                    shutil.rmtree(child, ignore_errors=True)
                    cleaned_count += 1
                except Exception:
                    pass
    return cleaned_count


def _safe_output_dir(data_dir: Path, raw_path: str | Path) -> Path | None:
    root = (data_dir / "outputs").resolve()
    try:
        raw_candidate = Path(raw_path)
        if raw_candidate.is_symlink():
            return None
        candidate = raw_candidate.resolve()
        candidate.relative_to(root)
        if candidate == root or candidate.parent != root:
            return None
    except (OSError, ValueError, TypeError):
        return None
    return candidate


def _directory_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    try:
        for child in path.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _delete_output_dir(data_dir: Path, raw_path: str | Path) -> int:
    output_dir = _safe_output_dir(data_dir, raw_path)
    if output_dir is None or not output_dir.is_dir():
        return 0
    size = _directory_size(output_dir)
    shutil.rmtree(output_dir, ignore_errors=True)
    return size


def prune_revisions(*, max_revisions_per_dataset: int, max_output_bytes: int) -> dict[str, int]:
    """Prune old revision rows and output directories within the data root."""
    data_dir = settings.data_dir
    cleanup_orphaned_outputs(data_dir)
    keep_limit = max(1, int(max_revisions_per_dataset))
    byte_limit = max(0, int(max_output_bytes))

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT rowid AS row_id, id, dataset_id, output_dir, created_at
            FROM revisions
            WHERE starred = 0
            ORDER BY created_at DESC, rowid DESC
            """
        ).fetchall()

        kept_by_dataset: dict[str, int] = {}
        retained: list[sqlite3.Row] = []
        candidates: list[sqlite3.Row] = []
        for row in rows:
            count = kept_by_dataset.get(row["dataset_id"], 0)
            if count < keep_limit:
                kept_by_dataset[row["dataset_id"]] = count + 1
                retained.append(row)
            else:
                candidates.append(row)

        def size_for(row: sqlite3.Row) -> int:
            output_dir = _safe_output_dir(data_dir, row["output_dir"])
            return _directory_size(output_dir) if output_dir else 0

        remaining_bytes = sum(size_for(row) for row in retained)
        selected = list(candidates)

        # If the configured byte budget is smaller than the retained history,
        # drop the oldest retained rows as a last resort while keeping at least
        # one newest revision globally.
        if remaining_bytes > byte_limit and retained:
            removed_retained = 0
            for row in sorted(retained, key=lambda item: (item["created_at"], item["row_id"])):
                if remaining_bytes <= byte_limit or len(retained) - removed_retained <= 1:
                    break
                selected.append(row)
                remaining_bytes -= size_for(row)
                removed_retained += 1

        if selected:
            placeholders = ",".join("?" for _ in selected)
            conn.execute(f"DELETE FROM revisions WHERE id IN ({placeholders})", [row["id"] for row in selected])

    removed_bytes = 0
    for row in selected:
        removed_bytes += _delete_output_dir(data_dir, row["output_dir"])
    cleanup_orphaned_outputs(data_dir)

    remaining_dirs = []
    outputs_root = data_dir / "outputs"
    if outputs_root.is_dir():
        remaining_dirs = [child for child in outputs_root.iterdir() if child.is_dir()]
    actual_remaining_bytes = sum(_directory_size(path) for path in remaining_dirs)
    return {
        "removed_revisions": len(selected),
        "removed_bytes": removed_bytes,
        "remaining_bytes": actual_remaining_bytes,
    }


def delete_revision(revision_id: str) -> bool:
    """Delete one revision and its data-root-scoped output directory."""
    data_dir = settings.data_dir
    with _connect() as conn:
        row = conn.execute("SELECT output_dir FROM revisions WHERE id = ?", (revision_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM revisions WHERE id = ?", (revision_id,))
    _delete_output_dir(data_dir, row["output_dir"])
    return True


def create_revision(
    dataset_id: str,
    code: str,
    preset: str,
    operation: str,
    output_dir: Path,
    success: bool,
    stderr: str = "",
) -> str:
    safe_output_dir = _safe_output_dir(settings.data_dir, output_dir)
    if safe_output_dir is None or not safe_output_dir.is_dir():
        raise ValueError("绘图产物目录必须是 outputs 下的直接子目录")
    revision_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO revisions(id, dataset_id, code, preset, operation, output_dir, success, stderr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (revision_id, dataset_id, code, preset, operation, str(safe_output_dir), int(success), stderr[-4000:]),
        )
    return revision_id


def list_revisions(dataset_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, dataset_id, preset, operation, success, created_at, label, starred
            FROM revisions
            WHERE dataset_id = ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (dataset_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "dataset_id": row["dataset_id"],
            "preset": row["preset"],
            "operation": row["operation"],
            "success": bool(row["success"]),
            "created_at": row["created_at"],
            "label": row["label"],
            "starred": bool(row["starred"]),
        }
        for row in rows
    ]


def get_revision(revision_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, dataset_id, code, preset, operation, output_dir, success, stderr, created_at, label, starred
            FROM revisions
            WHERE id = ?
            """,
            (revision_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "dataset_id": row["dataset_id"],
        "code": row["code"],
        "preset": row["preset"],
        "operation": row["operation"],
        "output_dir": row["output_dir"],
        "success": bool(row["success"]),
        "stderr": row["stderr"],
        "created_at": row["created_at"],
        "label": row["label"],
        "starred": bool(row["starred"]),
    }


def public_revision(revision: dict) -> dict:
    """Return revision metadata without exposing internal filesystem paths."""
    public_keys = (
        "id",
        "dataset_id",
        "code",
        "preset",
        "operation",
        "success",
        "stderr",
        "created_at",
        "label",
        "starred",
    )
    return {key: revision[key] for key in public_keys if key in revision}
