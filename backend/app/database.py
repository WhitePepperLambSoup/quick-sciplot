"""SQLite 持久化：数据集元信息与绘图版本历史。"""

import json
import sqlite3
import uuid
from pathlib import Path

from .config import settings


def _db_path() -> Path:
    return settings.data_dir / "history.sqlite3"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    settings.ensure_dirs()
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS revisions (
                id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                code TEXT NOT NULL,
                preset TEXT NOT NULL,
                operation TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                success INTEGER NOT NULL,
                stderr TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_revisions_dataset_created
            ON revisions(dataset_id, created_at DESC, id DESC);
            """
        )


def save_dataset(dataset: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO datasets(id, path, summary_json)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                path = excluded.path,
                summary_json = excluded.summary_json
            """,
            (dataset["id"], dataset["path"], json.dumps(dataset["summary"], ensure_ascii=False)),
        )


def get_dataset(dataset_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT id, path, summary_json FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "path": row["path"], "summary": json.loads(row["summary_json"])}


def create_revision(
    dataset_id: str,
    code: str,
    preset: str,
    operation: str,
    output_dir: Path,
    success: bool,
    stderr: str = "",
) -> str:
    revision_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO revisions(id, dataset_id, code, preset, operation, output_dir, success, stderr)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (revision_id, dataset_id, code, preset, operation, str(output_dir), int(success), stderr[-4000:]),
        )
    return revision_id


def list_revisions(dataset_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, dataset_id, preset, operation, success, created_at
            FROM revisions
            WHERE dataset_id = ?
            ORDER BY created_at DESC, id DESC
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
        }
        for row in rows
    ]


def get_revision(revision_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, dataset_id, code, preset, operation, output_dir, success, stderr, created_at
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
    }
