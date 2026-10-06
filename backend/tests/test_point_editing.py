"""Drag-to-correct data points: mark export, row matching and corrected datasets."""

import io
import json
import math
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import data_loader, database, main, point_editor
from app.config import SESSION_TOKEN, settings
from app.main import app

AUTH = TestClient(app, headers={"X-Session-Token": SESSION_TOKEN})


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()
    yield tmp_path
    main.DATASETS.clear()


FRAME = pd.DataFrame(
    {
        "group": ["a", "b", "a", "b", "a", "b"],
        "dose": [1, 2, 3, 4, 5, 6],
        "response": [2.0, 4.5, 3.25, 8.125, 6.5, 7.75],
        "count": [10, 20, 30, 40, 50, 60],
        "date": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"],
    }
)


def _upload(frame: pd.DataFrame = FRAME, name: str = "data.csv") -> dict:
    response = AUTH.post("/api/datasets", files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def _render(dataset_id: str, code: str) -> dict:
    response = AUTH.post("/api/plots/run", json={"dataset_id": dataset_id, "code": code})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["run"]["success"], result["run"]["stderr"]
    return result


def _points(revision_id: str) -> dict:
    response = AUTH.get(f"/api/plots/revisions/{revision_id}/points")
    assert response.status_code == 200, response.text
    return response.json()


def _set_values(point_set: dict) -> list[tuple]:
    return list(zip(point_set["rows"], point_set["xs"], point_set["ys"]))


# ------------------------------------------------------------ geometry export


def test_exported_image_geometry_lands_on_the_drawn_markers(isolated):
    dataset = _upload()
    code = (
        "fig, ax = plt.subplots(figsize=(5, 4))\n"
        "ax.scatter(df['dose'], df['response'], s=90, color='red')\n"
        "ax.set_yscale('log')\n"
        "ax.set_title('Dose response')\n"
    )
    result = _render(dataset["id"], code)
    # The large mark list stays on disk instead of every plot response.
    assert "sets" not in result["meta"]
    assert result["meta"]["image_box"][2] > 0.5
    points = _points(result["revision_id"])
    assert points["engine"] == "matplotlib"
    (scatter,) = points["sets"]
    geometry = points["axes"][scatter["axes"]]

    revision = database.get_revision(result["revision_id"])
    image = Image.open(f"{revision['output_dir']}/out.png").convert("RGB")
    width, height = image.size
    left, top, box_w, box_h = geometry["box"]

    def fraction(value, lim, scale):
        if scale == "log":
            return (math.log10(value) - math.log10(lim[0])) / (math.log10(lim[1]) - math.log10(lim[0]))
        return (value - lim[0]) / (lim[1] - lim[0])

    for x, y in zip(scatter["xs"], scatter["ys"]):
        px = (left + fraction(x, geometry["xlim"], geometry["x"]["scale"]) * box_w) * width
        py = (top + (1 - fraction(y, geometry["ylim"], geometry["y"]["scale"])) * box_h) * height
        assert image.getpixel((int(px), int(py))) == (255, 0, 0)


# ---------------------------------------------------------------- matching


def test_scatter_points_map_to_rows_and_columns(isolated):
    dataset = _upload()
    result = _render(dataset["id"], "fig, ax = plt.subplots()\nax.scatter(df['dose'], df['response'])\n")
    (scatter,) = _points(result["revision_id"])["sets"]
    assert scatter["kind"] == "scatter"
    assert scatter["x"] == {"column": "dose", "kind": "num", "scale": "linear", "editable": True}
    assert scatter["y"]["column"] == "response" and scatter["y"]["editable"] is True
    assert scatter["rows"] == [0, 1, 2, 3, 4, 5]


def test_filtered_sorted_subset_keeps_the_original_row_numbers(isolated):
    dataset = _upload()
    code = "sub = df[df['response'] > 3].sort_values('response', ascending=False)\nplt.plot(sub['dose'], sub['response'], 'o-')\n"
    result = _render(dataset["id"], code)
    (line,) = _points(result["revision_id"])["sets"]
    assert line["kind"] == "line"
    for row, x, y in _set_values(line):
        assert FRAME.loc[row, "dose"] == x and FRAME.loc[row, "response"] == y
    assert sorted(line["rows"]) == [1, 2, 3, 4, 5]


def test_seaborn_hue_scatter_and_strip_plot_match(isolated):
    dataset = _upload()
    code = (
        "import seaborn as sns\n"
        "fig, (a1, a2) = plt.subplots(1, 2)\n"
        "sns.scatterplot(data=df, x='dose', y='response', hue='group', ax=a1)\n"
        "sns.stripplot(data=df, x='group', y='response', ax=a2, jitter=0.25)\n"
    )
    result = _render(dataset["id"], code)
    sets = _points(result["revision_id"])["sets"]
    scatter = next(s for s in sets if s["x"]["column"] == "dose")
    assert sorted(scatter["rows"]) == list(range(6))
    strips = [s for s in sets if s["x"]["column"] == "group"]
    assert strips and all(s["x"]["kind"] == "cat" and s["x"]["editable"] is False for s in strips)
    assert all(s["y"]["column"] == "response" and s["y"]["editable"] for s in strips)
    for strip in strips:
        for row, _x, y in _set_values(strip):
            assert FRAME.loc[row, "response"] == y
    assert sorted(row for s in strips for row in s["rows"]) == list(range(6))


def test_series_plot_uses_the_row_number_as_x(isolated):
    dataset = _upload()
    result = _render(dataset["id"], "plt.plot(df['response'])\n")
    (line,) = _points(result["revision_id"])["sets"]
    assert line["x"].get("index") is True and line["x"]["editable"] is False
    assert line["y"]["column"] == "response"
    assert line["rows"] == list(range(6))


def test_bars_vertical_and_horizontal(isolated):
    frame = pd.DataFrame({"name": ["x", "y", "z"], "value": [3.0, -1.5, 4.0]})
    dataset = _upload(frame)
    code = "fig, (a1, a2) = plt.subplots(1, 2)\na1.bar(df['name'], df['value'], bottom=1)\na2.barh(df['name'], df['value'])\n"
    sets = _points(_render(dataset["id"], code)["revision_id"])["sets"]
    vertical = next(s for s in sets if s["orientation"] == "v")
    horizontal = next(s for s in sets if s["orientation"] == "h")
    assert vertical["x"]["column"] == "name" and vertical["x"]["editable"] is False
    assert vertical["y"]["column"] == "value" and vertical["y"]["editable"] is True
    assert vertical["bases"] == [1.0, 1.0, 1.0]
    assert vertical["x_display"] == ["x", "y", "z"] and "y_display" not in vertical
    assert vertical["rows"] == [0, 1, 2]
    assert horizontal["x"]["column"] == "value" and horizontal["x"]["editable"] is True
    assert horizontal["y"]["column"] == "name" and horizontal["y"]["editable"] is False


def test_dates_on_x_still_allow_editing_y(isolated):
    dataset = _upload()
    code = "df['date'] = pd.to_datetime(df['date'])\nfig, ax = plt.subplots()\nax.plot(df['date'], df['count'], marker='o')\n"
    (line,) = _points(_render(dataset["id"], code)["revision_id"])["sets"]
    assert line["x"]["kind"] == "date" and line["x"]["column"] == "date" and line["x"]["editable"] is False
    assert line["x_display"][:2] == ["2024-01-01", "2024-01-02"]
    assert line["y"]["column"] == "count" and line["y"]["editable"] is True
    assert line["rows"] == list(range(6))


def test_aggregated_or_transformed_marks_are_not_editable(isolated):
    dataset = _upload()
    code = (
        "import numpy as np\nimport seaborn as sns\n"
        "fig, (a1, a2) = plt.subplots(1, 2)\n"
        "sns.barplot(data=df, x='group', y='response', ax=a1, errorbar=None)\n"
        "a2.plot(df['dose'], np.log(df['response']), 'o')\n"
        "a2.axhline(1.0)\n"
    )
    points = _points(_render(dataset["id"], code)["revision_id"])
    assert points["sets"] == []
    assert points["unmatched"] >= 2


def test_duplicate_points_bind_to_distinct_rows(isolated):
    frame = pd.DataFrame({"x": [1, 1, 2, 2], "y": [5.0, 5.0, 6.0, 6.0], "g": ["a", "b", "a", "b"]})
    dataset = _upload(frame)
    code = (
        "fig, ax = plt.subplots()\n"
        "for name, part in df.groupby('g'):\n"
        "    ax.plot(part['x'], part['y'], 'o-', label=name)\n"
        "ax.legend()\n"
    )
    sets = _points(_render(dataset["id"], code)["revision_id"])["sets"]
    assert len(sets) == 2
    rows = [row for s in sets for row in s["rows"]]
    assert sorted(rows) == [0, 1, 2, 3]
    assert {s["label"] for s in sets} == {"a", "b"}
    assert all(s["ambiguous"] == 2 for s in sets)


def test_plotly_traces_match_including_typed_arrays(isolated):
    dataset = _upload()
    code = (
        "import plotly.express as px\n"
        "fig = px.scatter(df, x='dose', y='response', color='group')\n"
    )
    points = _points(_render(dataset["id"], code)["revision_id"])
    assert points["engine"] == "plotly"
    assert len(points["sets"]) == 2
    assert sorted(row for s in points["sets"] for row in s["rows"]) == list(range(6))
    assert all(s["y"]["column"] == "response" and s["y"]["editable"] for s in points["sets"])

    bar_code = "import plotly.graph_objects as go\nfig = go.Figure(go.Bar(x=df['group'] + df['dose'].astype(str), y=df['count']))\n"
    bar_frame = FRAME.assign(label=FRAME["group"] + FRAME["dose"].astype(str))
    bar_dataset = _upload(bar_frame, "bars.csv")
    (bar,) = _points(_render(bar_dataset["id"], bar_code)["revision_id"])["sets"]
    assert bar["kind"] == "bar" and bar["x"]["column"] == "label" and bar["x"]["kind"] == "cat"
    assert bar["y"]["column"] == "count" and bar["y"]["editable"]
    assert bar["xs"][0] == "a1"


def test_plotly_typed_array_decoder():
    raw = np.array([1.5, -2.0, 3.25])
    encoded = {"dtype": "f8", "bdata": __import__("base64").b64encode(raw.tobytes()).decode()}
    assert point_editor._plotly_array(encoded) == [1.5, -2.0, 3.25]
    assert point_editor._plotly_array({"dtype": "f8", "bdata": "AAA="}) is None


def test_untrusted_meta_is_validated(isolated):
    frame = FRAME.copy()
    meta = {
        "axes": [{"box": [0, 0, 1, 1], "xlim": [0, 10], "ylim": [0, 10], "x": {"kind": "num"}, "y": {"kind": "evil"}}, "junk"],
        "sets": [
            {"axes": 0, "kind": "scatter", "x": [1, 2], "y": [2.0, 4.5]},
            {"axes": 5, "kind": "scatter", "x": [1], "y": [2.0]},
            {"axes": 0, "kind": "scatter", "x": [1, "a"], "y": [2.0, 1]},
            {"axes": 0, "kind": "scatter", "x": [float("nan")], "y": [2.0]},
            {"axes": 0, "kind": "unknown", "x": [1], "y": [2.0]},
            {"axes": 0, "kind": "scatter", "x": list(range(5000)), "y": list(range(5000))},
        ],
    }
    result = point_editor.matplotlib_point_sets(meta, frame, "")
    assert len(result["sets"]) == 1
    assert result["sets"][0]["rows"] == [0, 1]
    assert result["axes"][1] is None


# ------------------------------------------------------------- cell editing


def test_apply_cell_edits_types_and_log():
    frame = pd.DataFrame({"n": [1, 2, 3], "f": [1.5, 2.5, 3.5], "s": ["a", "b", "c"]})
    edited, log = point_editor.apply_cell_edits(
        frame,
        [
            {"row": 0, "column": "n", "value": 10.0},
            {"row": 1, "column": "f", "value": None},
            {"row": 2, "column": "s", "value": "z"},
            {"row": 2, "column": "f", "value": 3.5},  # unchanged: not logged
            {"row": 0, "column": "n", "value": 11.0},  # later edit of the same cell wins
        ],
    )
    assert pd.api.types.is_integer_dtype(edited["n"]) and edited.loc[0, "n"] == 11
    assert math.isnan(edited.loc[1, "f"])
    assert edited.loc[2, "s"] == "z"
    assert frame.loc[0, "n"] == 1  # the input frame is not modified
    assert log == [
        {"row": 0, "column": "n", "old": 1, "new": 11},
        {"row": 1, "column": "f", "old": 2.5, "new": None},
        {"row": 2, "column": "s", "old": "c", "new": "z"},
    ]
    fractional, _ = point_editor.apply_cell_edits(frame, [{"row": 0, "column": "n", "value": 1.25}])
    assert fractional["n"].dtype == "float64" and fractional.loc[0, "n"] == 1.25


@pytest.mark.parametrize(
    "edit, message",
    [
        ({"row": 9, "column": "n", "value": 1}, "行号"),
        ({"row": 0, "column": "missing", "value": 1}, "列不存在"),
        ({"row": 0, "column": "n", "value": "abc"}, "必须是数字"),
        ({"row": 0, "column": "n", "value": 1}, "相同"),
    ],
)
def test_apply_cell_edits_rejects_bad_edits(edit, message):
    frame = pd.DataFrame({"n": [1, 2, 3]})
    with pytest.raises(data_loader.DataError, match=message):
        point_editor.apply_cell_edits(frame, [edit])


def test_edit_cells_creates_a_versioned_dataset_and_rerenders(isolated):
    dataset = _upload()
    code = "fig, ax = plt.subplots()\nax.scatter(df['dose'], df['response'])\n"
    response = AUTH.post(
        f"/api/datasets/{dataset['id']}/edit-cells",
        json={
            "edits": [{"row": 3, "column": "response", "value": 5.5}, {"row": 0, "column": "dose", "value": 1.5}],
            "note": "  typo in   lab notebook ",
            "code": code,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    corrected = body["dataset"]
    assert corrected["id"] != dataset["id"]
    assert corrected["name"] == "data.csv（修正 1）"
    assert corrected["provenance"] == {
        "kind": "cell-edits",
        "parent_id": dataset["id"],
        "parent_name": "data.csv",
        "root_id": dataset["id"],
        "root_name": "data.csv",
        "step": 1,
        "edit_count": 2,
    }
    assert body["edits"] == [
        {"row": 3, "column": "response", "old": 8.125, "new": 5.5},
        {"row": 0, "column": "dose", "old": 1, "new": 1.5},
    ]
    assert body["plot"]["run"]["success"]
    revision = database.get_revision(body["plot"]["revision_id"])
    assert revision["dataset_id"] == corrected["id"] and revision["operation"] == "data-edit"
    (scatter,) = _points(body["plot"]["revision_id"])["sets"]
    assert (3, 4.0, 5.5) in _set_values(scatter)

    # The original data is untouched.
    original = data_loader.load_dataframe(database.get_dataset(dataset["id"])["path"])
    assert original.loc[3, "response"] == 8.125

    second = AUTH.post(
        f"/api/datasets/{corrected['id']}/edit-cells",
        json={"edits": [{"row": 3, "column": "response", "value": 5.75}]},
    ).json()
    assert "plot" not in second
    assert second["dataset"]["name"] == "data.csv（修正 2）"
    assert second["dataset"]["provenance"]["step"] == 2
    assert second["dataset"]["provenance"]["root_id"] == dataset["id"]
    assert second["dataset"]["provenance"]["edit_count"] == 3

    log = AUTH.get(f"/api/datasets/{second['dataset']['id']}/edits").json()["provenance"]
    assert [entry["step"] for entry in log["edits"]] == [1, 1, 2]
    assert log["edits"][0]["note"] == "typo in lab notebook"
    assert log["edits"][2] == {**log["edits"][2], "row": 3, "column": "response", "old": 5.5, "new": 5.75}

    listed = {item["id"]: item for item in AUTH.get("/api/datasets").json()["datasets"]}
    assert listed[second["dataset"]["id"]]["provenance"]["edit_count"] == 3
    assert "edits" not in listed[second["dataset"]["id"]]["provenance"]
    assert "provenance" not in listed[dataset["id"]]

    # Provenance survives a restart (in-memory cache cleared).
    main.DATASETS.clear()
    assert AUTH.get(f"/api/datasets/{second['dataset']['id']}").json()["provenance"]["step"] == 2


def test_edit_cells_validation_errors(isolated):
    dataset = _upload()
    bad_row = AUTH.post(f"/api/datasets/{dataset['id']}/edit-cells", json={"edits": [{"row": 99, "column": "dose", "value": 1}]})
    assert bad_row.status_code == 400 and "行号" in bad_row.json()["detail"]
    empty = AUTH.post(f"/api/datasets/{dataset['id']}/edit-cells", json={"edits": []})
    assert empty.status_code == 422
    negative = AUTH.post(f"/api/datasets/{dataset['id']}/edit-cells", json={"edits": [{"row": -1, "column": "dose", "value": 1}]})
    assert negative.status_code == 422
    missing = AUTH.post("/api/datasets/nope/edit-cells", json={"edits": [{"row": 0, "column": "dose", "value": 1}]})
    assert missing.status_code == 404
    assert len(AUTH.get("/api/datasets").json()["datasets"]) == 1


def test_edit_cells_keeps_the_dataset_when_the_render_fails(isolated):
    dataset = _upload()
    response = AUTH.post(
        f"/api/datasets/{dataset['id']}/edit-cells",
        json={"edits": [{"row": 0, "column": "dose", "value": 9}], "code": "import os\n"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "plot" not in body and "安全检查" in body["plot_error"]
    assert body["dataset"]["provenance"]["edit_count"] == 1


def test_bundle_of_a_corrected_dataset_ships_the_edit_log(isolated):
    dataset = _upload()
    body = AUTH.post(
        f"/api/datasets/{dataset['id']}/edit-cells",
        json={
            "edits": [{"row": 1, "column": "response", "value": 4.0}],
            "note": "re-measured",
            "code": "plt.plot(df['dose'], df['response'], 'o')\n",
        },
    ).json()
    archive = zipfile.ZipFile(io.BytesIO(AUTH.get(f"/api/plots/revisions/{body['plot']['revision_id']}/export/bundle").content))
    names = set(archive.namelist())
    assert {"data.csv", "data_corrections.csv", "README.txt", "revision.json"} <= names
    corrections = pd.read_csv(io.BytesIO(archive.read("data_corrections.csv")))
    assert corrections.to_dict("records") == [
        {
            "step": 1,
            "data_row": 2,
            "column": "response",
            "old_value": 4.5,
            "new_value": 4.0,
            "edited_at": corrections.loc[0, "edited_at"],
            "note": "re-measured",
        }
    ]
    assert json.loads(archive.read("revision.json"))["data_corrections"]["edit_count"] == 1
    assert "data_corrections.csv" in archive.read("README.txt").decode()
    assert pd.read_csv(io.BytesIO(archive.read("data.csv"))).loc[1, "response"] == 4.0


def test_points_endpoint_errors(isolated):
    assert AUTH.get("/api/plots/revisions/missing/points").status_code == 404
