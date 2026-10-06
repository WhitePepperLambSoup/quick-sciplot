"""Reproducible exports: standalone scripts, project bundles, thumbnails and zips."""

import io
import json
import zipfile
from pathlib import Path

from PIL import Image

from . import point_editor, sandbox

ARTIFACT_NAMES = {
    "png": "figure.png",
    "svg": "figure.svg",
    "pdf": "figure.pdf",
    "eps": "figure.eps",
    "plotly": "figure.plotly.json",
}
_OUTPUT_FILES = {"png": "out.png", "svg": "out.svg", "pdf": "out.pdf", "eps": "out.eps", "plotly": "out.plotly.json"}
THUMBNAIL_SIZE = (480, 360)


def standalone_script(revision: dict) -> str:
    return sandbox.build_standalone_script(revision["code"], revision.get("preset"), data_file="data.csv")


def _readme(revision: dict, dataset_name: str, provenance: dict | None = None) -> str:
    corrections = ""
    if provenance:
        corrections = (
            "data_corrections.csv  Every cell corrected in Quick SciPlot (row, column, old and new value,\n"
            f"                      time and note): {provenance.get('edit_count', 0)} edit(s) relative to\n"
            f"                      \"{provenance.get('root_name') or 'the original dataset'}\".\n"
        )
    return (
        "Quick SciPlot project bundle\n"
        "============================\n\n"
        f"Dataset:   {dataset_name}\n"
        f"Revision:  {revision['id']}\n"
        f"Preset:    {revision.get('preset') or 'default'}\n"
        f"Created:   {revision.get('created_at') or ''}\n\n"
        "Files\n"
        "-----\n"
        "data.csv          The dataset used for the figure.\n"
        f"{corrections}"
        "plot.py           Standalone plotting script; run `python plot.py` in this folder.\n"
        "figure.*          The rendered outputs from Quick SciPlot.\n"
        "revision.json     Revision metadata.\n\n"
        "Requirements: pandas and matplotlib, plus seaborn/scipy/statsmodels/plotly if plot.py imports them.\n"
    )


def project_bundle(
    revision: dict,
    dataset_path: Path,
    dataset_name: str,
    output_dir: Path,
    provenance: dict | None = None,
) -> bytes:
    """Zip with data.csv, plot.py, rendered outputs and metadata for one revision.

    A corrected dataset also ships its full edit log as data_corrections.csv.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(dataset_path, "data.csv")
        archive.writestr("plot.py", standalone_script(revision))
        for kind, filename in _OUTPUT_FILES.items():
            path = output_dir / filename
            if path.is_file():
                archive.write(path, ARTIFACT_NAMES[kind])
        metadata = {
            key: revision.get(key)
            for key in ("id", "dataset_id", "preset", "operation", "created_at", "label", "starred")
        }
        metadata["dataset_name"] = dataset_name
        if provenance:
            metadata["data_corrections"] = point_editor.public_provenance(provenance)
            archive.writestr("data_corrections.csv", point_editor.edits_csv(provenance))
        archive.writestr("revision.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", _readme(revision, dataset_name, provenance))
    return buffer.getvalue()


def thumbnail(output_dir: Path) -> bytes | None:
    """Small PNG preview of a revision's main image, or None if it has no PNG."""
    source = output_dir / "out.png"
    if not source.is_file():
        return None
    with Image.open(source) as image:
        image = image.convert("RGBA") if image.mode not in ("RGB", "RGBA") else image.copy()
        image.thumbnail(THUMBNAIL_SIZE)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return out.getvalue()


def revisions_zip(entries: list[tuple[str, Path]], kind: str) -> bytes:
    """Zip one output format from several revisions; ``entries`` are (name stem, output_dir)."""
    if kind not in _OUTPUT_FILES:
        raise ValueError(f"不支持的导出格式: {kind}")
    suffix = ARTIFACT_NAMES[kind].split(".", 1)[1]
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for stem, output_dir in entries:
            path = output_dir / _OUTPUT_FILES[kind]
            if not path.is_file():
                continue
            safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in stem).strip("._") or "figure"
            name = f"{safe}.{suffix}"
            counter = 2
            while name in used:
                name = f"{safe}-{counter}.{suffix}"
                counter += 1
            used.add(name)
            archive.write(path, name)
    return buffer.getvalue()
