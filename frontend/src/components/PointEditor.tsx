import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { PlotlyElement, PlotlyFullAxis } from "plotly.js-dist-min";
import { getRevisionPoints } from "../api";
import type { CellEdit, PointSet, PointSetsResponse } from "../types";
import type { Language } from "./ParameterInput";

/** Drag-to-correct data points on the preview.
 *
 * ``usePointEditor`` loads the editable marks of a revision (each bound to a
 * dataset row by the backend) and keeps the pending cell edits with undo/redo.
 * ``PointOverlay`` draws handles over the figure (Matplotlib image or Plotly
 * graph) and turns drags, nudges and box selections into cell edits;
 * ``PointEditPanel`` lists the edits and applies them as a new dataset version.
 */

export type AxisLock = "y" | "x" | "free";
type Axis = "x" | "y";

export interface PendingEdit {
  row: number;
  column: string;
  oldValue: number;
  /** null clears the cell (missing value). */
  newValue: number | null;
}

export interface EditablePoint {
  key: string;
  set: PointSet;
  index: number;
  row: number;
}

type Drafts = Map<string, number | null>;

const AXES: Axis[] = ["x", "y"];

export function cellKey(row: number, column: string): string {
  return `${row}\u0001${column}`;
}

function valueAxis(set: PointSet): Axis | null {
  if (set.kind !== "bar") return null;
  return set.orientation === "h" ? "x" : "y";
}

function rawValue(set: PointSet, axis: Axis, index: number): number | string {
  return (axis === "x" ? set.xs : set.ys)[index];
}

/** What to show for a point on an axis that is not edited (category label, date, ...). */
function displayValue(set: PointSet, axis: Axis, index: number): string {
  const labels = axis === "x" ? set.x_display : set.y_display;
  return labels?.[index] ?? String(rawValue(set, axis, index));
}

export function formatValue(value: number | null | undefined, zh = true): string {
  if (value === null || value === undefined) return zh ? "缺失" : "missing";
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return String(value);
  return Number(value.toPrecision(6)).toString();
}

function sameNumber(a: number | null, b: number | null): boolean {
  if (a === null || b === null) return a === b;
  return a === b || Math.abs(a - b) <= 1e-12 * Math.max(1, Math.abs(a), Math.abs(b));
}

// ---------------------------------------------------------------- the editor

export function usePointEditor(revisionId: string | undefined, active: boolean) {
  const [data, setData] = useState<PointSetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingEdit[]>([]);
  const [undoStack, setUndoStack] = useState<PendingEdit[][]>([]);
  const [redoStack, setRedoStack] = useState<PendingEdit[][]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lock, setLock] = useState<AxisLock>("y");
  const [note, setNote] = useState("");
  const datasetRef = useRef<string | null>(null);

  const resetEdits = useCallback(() => {
    setPending([]);
    setUndoStack([]);
    setRedoStack([]);
    setNote("");
  }, []);

  useEffect(() => {
    if (!active || !revisionId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRevisionPoints(revisionId)
      .then((next) => {
        if (cancelled) return;
        // Pending edits address rows of one dataset; drop them if the figure
        // now shows another dataset.
        if (datasetRef.current && datasetRef.current !== next.dataset_id) resetEdits();
        datasetRef.current = next.dataset_id;
        setData(next);
        setSelected(new Set());
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : String(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [active, revisionId, resetEdits]);

  const points = useMemo<EditablePoint[]>(() => {
    if (!data) return [];
    const out: EditablePoint[] = [];
    for (const set of data.sets) {
      if (!set.x.editable && !set.y.editable) continue;
      set.rows.forEach((row, index) => out.push({ key: `${set.id}:${index}`, set, index, row }));
    }
    return out;
  }, [data]);

  const pointByKey = useMemo(() => new Map(points.map((point) => [point.key, point])), [points]);
  const pendingMap = useMemo(() => new Map(pending.map((edit) => [cellKey(edit.row, edit.column), edit])), [pending]);

  /** The cell value an axis of a point stands for (bars: the bar value, not its end). */
  const originalValue = useCallback((point: EditablePoint, axis: Axis): number => Number(rawValue(point.set, axis, point.index)), []);

  const cellValue = useCallback(
    (point: EditablePoint, axis: Axis, drafts?: Drafts | null): number | null => {
      const column = point.set[axis].column;
      if (column) {
        const key = cellKey(point.row, column);
        if (drafts?.has(key)) return drafts.get(key) ?? null;
        const edit = pendingMap.get(key);
        if (edit) return edit.newValue;
      }
      return originalValue(point, axis);
    },
    [originalValue, pendingMap],
  );

  const commit = useCallback(
    (next: PendingEdit[]) => {
      setUndoStack((stack) => [...stack.slice(-199), pending]);
      setRedoStack([]);
      setPending(next);
    },
    [pending],
  );

  /** Merge cell changes ([row, column, value]) into the pending edits. */
  const applyChanges = useCallback(
    (changes: { point: EditablePoint; axis: Axis; value: number | null }[]) => {
      const next = [...pending];
      let changed = false;
      for (const { point, axis, value } of changes) {
        const column = point.set[axis].column;
        if (!column || !point.set[axis].editable) continue;
        const oldValue = originalValue(point, axis);
        const index = next.findIndex((edit) => edit.row === point.row && edit.column === column);
        if (sameNumber(value, oldValue)) {
          if (index >= 0) {
            next.splice(index, 1);
            changed = true;
          }
        } else if (index >= 0) {
          if (!sameNumber(next[index].newValue, value)) {
            next[index] = { ...next[index], newValue: value };
            changed = true;
          }
        } else {
          next.push({ row: point.row, column, oldValue, newValue: value });
          changed = true;
        }
      }
      if (changed) commit(next);
    },
    [commit, originalValue, pending],
  );

  const revertKeys = useCallback(
    (cells: Set<string>) => {
      const next = pending.filter((edit) => !cells.has(cellKey(edit.row, edit.column)));
      if (next.length !== pending.length) commit(next);
    },
    [commit, pending],
  );

  const undo = useCallback(() => {
    if (undoStack.length === 0) return;
    setRedoStack((stack) => [...stack, pending]);
    setPending(undoStack[undoStack.length - 1]);
    setUndoStack((stack) => stack.slice(0, -1));
  }, [pending, undoStack]);

  const redo = useCallback(() => {
    if (redoStack.length === 0) return;
    setUndoStack((stack) => [...stack, pending]);
    setPending(redoStack[redoStack.length - 1]);
    setRedoStack((stack) => stack.slice(0, -1));
  }, [pending, redoStack]);

  /** Editable cells of the selected points along the axes the lock allows. */
  const selectedCells = useCallback(
    (axes: Axis[] = AXES) => {
      const cells: { point: EditablePoint; axis: Axis }[] = [];
      for (const key of selected) {
        const point = pointByKey.get(key);
        if (!point) continue;
        for (const axis of axes) {
          if (point.set[axis].editable && point.set[axis].column) cells.push({ point, axis });
        }
      }
      return cells;
    },
    [pointByKey, selected],
  );

  /** Mark the selected points' value as missing (the axis the lock allows, y first). */
  const clearSelected = useCallback(() => {
    const changes: { point: EditablePoint; axis: Axis; value: null }[] = [];
    for (const key of selected) {
      const point = pointByKey.get(key);
      if (!point) continue;
      const order: Axis[] = lock === "x" ? ["x", "y"] : ["y", "x"];
      const axis = order.find((candidate) => point.set[candidate].editable && point.set[candidate].column);
      if (axis) changes.push({ point, axis, value: null });
    }
    applyChanges(changes);
  }, [applyChanges, lock, pointByKey, selected]);

  const revertSelected = useCallback(() => {
    revertKeys(new Set(selectedCells().map(({ point, axis }) => cellKey(point.row, point.set[axis].column as string))));
  }, [revertKeys, selectedCells]);

  const edits: CellEdit[] = useMemo(() => pending.map((edit) => ({ row: edit.row, column: edit.column, value: edit.newValue })), [pending]);

  return {
    data,
    loading,
    error,
    points,
    pointByKey,
    pending,
    pendingMap,
    edits,
    selected,
    setSelected,
    lock,
    setLock,
    note,
    setNote,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    undo,
    redo,
    resetEdits,
    applyChanges,
    revertKeys,
    clearSelected,
    revertSelected,
    originalValue,
    cellValue,
  };
}

export type PointEditorState = ReturnType<typeof usePointEditor>;

// ----------------------------------------------------------------- projection

interface Projector {
  /** Overlay pixel of an axis coordinate (NaN when it cannot be placed). */
  toPx: (set: PointSet, axis: Axis, coord: number | string) => number;
  /** Axis coordinate at an overlay pixel. */
  toCoord: (set: PointSet, axis: Axis, px: number) => number;
  base: (set: PointSet, index: number) => number;
}

function scaleFraction(value: number, lim: [number, number], scale: string): number {
  if (scale === "log") {
    if (value <= 0 || lim[0] <= 0 || lim[1] <= 0) return NaN;
    return (Math.log10(value) - Math.log10(lim[0])) / (Math.log10(lim[1]) - Math.log10(lim[0]));
  }
  return (value - lim[0]) / (lim[1] - lim[0] || 1e-12);
}

function scaleValue(fraction: number, lim: [number, number], scale: string): number {
  if (scale === "log") {
    const low = Math.log10(lim[0]);
    return 10 ** (low + fraction * (Math.log10(lim[1]) - low));
  }
  return lim[0] + fraction * (lim[1] - lim[0]);
}

function matplotlibProjector(data: PointSetsResponse, width: number, height: number): Projector {
  return {
    toPx(set, axis, coord) {
      const geometry = data.axes[set.axes ?? -1];
      const value = Number(coord);
      if (!geometry || !Number.isFinite(value)) return NaN;
      const [left, top, boxWidth, boxHeight] = geometry.box;
      if (axis === "x") return (left + scaleFraction(value, geometry.xlim, geometry.x.scale) * boxWidth) * width;
      return (top + (1 - scaleFraction(value, geometry.ylim, geometry.y.scale)) * boxHeight) * height;
    },
    toCoord(set, axis, px) {
      const geometry = data.axes[set.axes ?? -1];
      if (!geometry) return NaN;
      const [left, top, boxWidth, boxHeight] = geometry.box;
      if (axis === "x") return scaleValue((px / width - left) / boxWidth, geometry.xlim, geometry.x.scale);
      return scaleValue(1 - (px / height - top) / boxHeight, geometry.ylim, geometry.y.scale);
    },
    base: (set, index) => set.bases?.[index] ?? 0,
  };
}

function plotlyProjector(graph: PlotlyElement, offset: { x: number; y: number }): Projector {
  const axisOf = (set: PointSet, axis: Axis) => {
    const ref = axis === "x" ? set.xref || "x" : set.yref || "y";
    const candidate = graph._fullLayout?.[`${axis}axis${ref.slice(1)}`] as PlotlyFullAxis | undefined;
    return candidate && typeof candidate.d2p === "function" ? candidate : undefined;
  };
  return {
    toPx(set, axis, coord) {
      const target = axisOf(set, axis);
      if (!target) return NaN;
      const px = target.d2p(coord);
      return Number.isFinite(px) ? (axis === "x" ? offset.x : offset.y) + target._offset + px : NaN;
    },
    toCoord(set, axis, px) {
      const target = axisOf(set, axis);
      if (!target) return NaN;
      return Number(target.p2d(px - (axis === "x" ? offset.x : offset.y) - target._offset));
    },
    base(set, index) {
      // Stacked/relative bars: Plotly's computed base of this bar.
      const base = graph.calcdata?.[set.trace ?? -1]?.[index]?.b;
      return typeof base === "number" && Number.isFinite(base) ? base : set.bases?.[index] ?? 0;
    },
  };
}

/** Round a dragged value to what one screen pixel can resolve. */
function roundToPixel(value: number, resolution: number): number {
  if (!Number.isFinite(resolution) || resolution <= 0) return value;
  const digits = Math.min(12, Math.max(0, Math.ceil(-Math.log10(resolution))));
  return Number(value.toFixed(digits));
}

// -------------------------------------------------------------------- overlay

interface PointOverlayProps {
  editor: PointEditorState;
  language: Language;
  busy: boolean;
  /** Plotly graph div when the figure is interactive; null for Matplotlib images. */
  graph?: PlotlyElement | null;
  /** Bumped whenever the Plotly layout changes (zoom, pan, resize). */
  layoutTick?: number;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  keys: string[];
  grabbed: string;
  origin: Map<string, { x: number; y: number }>;
  moved: boolean;
}

interface BandState {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  additive: boolean;
}

function isTypingTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return Boolean(element && (element.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName)));
}

export function PointOverlay({ editor, language, busy, graph, layoutTick = 0 }: PointOverlayProps) {
  const zh = language === "zh";
  const svgRef = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [graphOffset, setGraphOffset] = useState({ x: 0, y: 0 });
  const [drafts, setDrafts] = useState<Drafts | null>(null);
  const [band, setBand] = useState<BandState | null>(null);
  const [hint, setHint] = useState<{ x: number; y: number; text: string } | null>(null);
  const dragRef = useRef<DragState | null>(null);

  useEffect(() => {
    const element = svgRef.current;
    if (!element) return;
    const update = () => {
      const rect = element.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useLayoutEffect(() => {
    if (!graph || !svgRef.current) return;
    const graphRect = graph.getBoundingClientRect();
    const overlayRect = svgRef.current.getBoundingClientRect();
    setGraphOffset({ x: graphRect.left - overlayRect.left, y: graphRect.top - overlayRect.top });
  }, [graph, layoutTick, size]);

  const { data, points, cellValue, applyChanges, selected, setSelected, lock } = editor;

  const projector = useMemo<Projector | null>(() => {
    if (!data || size.width === 0) return null;
    if (data.engine === "plotly") return graph ? plotlyProjector(graph, graphOffset) : null;
    if (data.engine === "matplotlib") return matplotlibProjector(data, size.width, size.height);
    return null;
    // layoutTick: Plotly axes mutate in place on zoom/pan.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, size, graph, graphOffset, layoutTick]);

  /** Axis coordinate where a point is drawn (bars: the end of the bar). */
  const coordinate = useCallback(
    (point: EditablePoint, axis: Axis, current: Drafts | null, useEdits = true): number | string | null => {
      const spec = point.set[axis];
      if (!spec.editable || !spec.column) return rawValue(point.set, axis, point.index);
      const value = useEdits ? cellValue(point, axis, current) : editor.originalValue(point, axis);
      if (value === null) return null;
      return valueAxis(point.set) === axis && projector ? value + projector.base(point.set, point.index) : value;
    },
    [cellValue, editor, projector],
  );

  const placed = useMemo(() => {
    if (!projector) return [];
    return points.map((point) => {
      const ox = projector.toPx(point.set, "x", coordinate(point, "x", null, false) ?? NaN);
      const oy = projector.toPx(point.set, "y", coordinate(point, "y", null, false) ?? NaN);
      const cx = coordinate(point, "x", drafts);
      const cy = coordinate(point, "y", drafts);
      const cleared = cx === null || cy === null;
      const x = cleared ? ox : projector.toPx(point.set, "x", cx);
      const y = cleared ? oy : projector.toPx(point.set, "y", cy);
      return { point, x, y, ox, oy, cleared, moved: !cleared && (Math.abs(x - ox) > 0.5 || Math.abs(y - oy) > 0.5) };
    });
  }, [coordinate, drafts, points, projector]);

  const placedByKey = useMemo(() => new Map(placed.map((item) => [item.point.key, item])), [placed]);

  const localPoint = (event: { clientX: number; clientY: number }) => {
    const rect = svgRef.current?.getBoundingClientRect();
    return rect ? { x: event.clientX - rect.left, y: event.clientY - rect.top } : { x: 0, y: 0 };
  };

  const describe = useCallback(
    (point: EditablePoint, current: Drafts | null) => {
      const parts: string[] = [];
      for (const axis of AXES) {
        const spec = point.set[axis];
        if (!spec.column) continue;
        if (spec.editable) {
          const before = editor.originalValue(point, axis);
          const after = cellValue(point, axis, current);
          parts.push(sameNumber(before, after) ? `${spec.column} = ${formatValue(after, zh)}` : `${spec.column}: ${formatValue(before, zh)} → ${formatValue(after, zh)}`);
        } else {
          parts.push(`${spec.column} = ${displayValue(point.set, axis, point.index)}`);
        }
      }
      return `${zh ? `第 ${point.row + 1} 行` : `Row ${point.row + 1}`} · ${parts.join(" · ")}`;
    },
    [cellValue, editor, zh],
  );

  /** Drafts for moving the dragged points by (dx, dy) overlay pixels. */
  const draftsFor = useCallback(
    (drag: DragState, dx: number, dy: number): Drafts => {
      const next: Drafts = new Map();
      if (!projector) return next;
      for (const key of drag.keys) {
        const point = editor.pointByKey.get(key);
        const origin = drag.origin.get(key);
        if (!point || !origin) continue;
        for (const axis of AXES) {
          if ((lock === "y" && axis === "x") || (lock === "x" && axis === "y")) continue;
          const spec = point.set[axis];
          if (!spec.editable || !spec.column) continue;
          const pixel = axis === "x" ? origin.x + dx : origin.y + dy;
          const coord = projector.toCoord(point.set, axis, pixel);
          if (!Number.isFinite(coord)) continue;
          const resolution = Math.abs(projector.toCoord(point.set, axis, pixel + 1) - coord);
          const base = valueAxis(point.set) === axis ? projector.base(point.set, point.index) : 0;
          next.set(cellKey(point.row, spec.column), roundToPixel(coord - base, resolution));
        }
      }
      return next;
    },
    [editor.pointByKey, lock, projector],
  );

  const commitDrafts = useCallback(
    (current: Drafts, keys: string[]) => {
      const changes: { point: EditablePoint; axis: Axis; value: number | null }[] = [];
      for (const key of keys) {
        const point = editor.pointByKey.get(key);
        if (!point) continue;
        for (const axis of AXES) {
          const column = point.set[axis].column;
          if (column && current.has(cellKey(point.row, column))) {
            changes.push({ point, axis, value: current.get(cellKey(point.row, column)) ?? null });
          }
        }
      }
      applyChanges(changes);
    },
    [applyChanges, editor.pointByKey],
  );

  const onHandleDown = (event: React.PointerEvent, key: string) => {
    if (busy || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    let next = new Set(selected);
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      if (next.has(key)) next.delete(key);
      else next.add(key);
    } else if (!next.has(key)) {
      next = new Set([key]);
    }
    setSelected(next);
    if (!next.has(key)) return;
    const origin = new Map<string, { x: number; y: number }>();
    for (const selectedKey of next) {
      const item = placedByKey.get(selectedKey);
      if (item && !item.cleared && Number.isFinite(item.x) && Number.isFinite(item.y)) origin.set(selectedKey, { x: item.x, y: item.y });
    }
    const start = localPoint(event);
    dragRef.current = { pointerId: event.pointerId, startX: start.x, startY: start.y, keys: [...origin.keys()], grabbed: key, origin, moved: false };
    svgRef.current?.setPointerCapture(event.pointerId);
  };

  const onBackgroundDown = (event: React.PointerEvent) => {
    if (busy || event.button !== 0) return;
    const start = localPoint(event);
    setBand({ x0: start.x, y0: start.y, x1: start.x, y1: start.y, additive: event.shiftKey || event.ctrlKey || event.metaKey });
    svgRef.current?.setPointerCapture(event.pointerId);
  };

  const onMove = (event: React.PointerEvent) => {
    const position = localPoint(event);
    const drag = dragRef.current;
    if (drag) {
      let dx = position.x - drag.startX;
      let dy = position.y - drag.startY;
      if (lock === "y") dx = 0;
      if (lock === "x") dy = 0;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
      drag.moved = true;
      const next = draftsFor(drag, dx, dy);
      setDrafts(next);
      const grabbed = editor.pointByKey.get(drag.grabbed);
      if (grabbed) setHint({ x: position.x, y: position.y, text: describe(grabbed, next) });
      return;
    }
    if (band) setBand({ ...band, x1: position.x, y1: position.y });
  };

  const onUp = (event: React.PointerEvent) => {
    if (svgRef.current?.hasPointerCapture(event.pointerId)) svgRef.current.releasePointerCapture(event.pointerId);
    const drag = dragRef.current;
    dragRef.current = null;
    if (drag) {
      if (drag.moved && drafts) commitDrafts(drafts, drag.keys);
      setDrafts(null);
      setHint(null);
      return;
    }
    if (band) {
      const [left, right] = [Math.min(band.x0, band.x1), Math.max(band.x0, band.x1)];
      const [top, bottom] = [Math.min(band.y0, band.y1), Math.max(band.y0, band.y1)];
      const inside = placed.filter((item) => item.x >= left && item.x <= right && item.y >= top && item.y <= bottom).map((item) => item.point.key);
      if (right - left < 3 && bottom - top < 3) {
        if (!band.additive) setSelected(new Set());
      } else {
        setSelected(new Set(band.additive ? [...selected, ...inside] : inside));
      }
      setBand(null);
    }
  };

  // Keyboard: undo/redo, nudge, clear, deselect.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (busy || isTypingTarget(event.target)) return;
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (mod && key === "z") {
        event.preventDefault();
        if (event.shiftKey) editor.redo();
        else editor.undo();
      } else if (mod && key === "y") {
        event.preventDefault();
        editor.redo();
      } else if (key === "escape" && selected.size > 0) {
        event.preventDefault();
        event.stopPropagation();
        setSelected(new Set());
      } else if ((key === "delete" || key === "backspace") && selected.size > 0) {
        event.preventDefault();
        editor.clearSelected();
      } else if (key.startsWith("arrow") && selected.size > 0 && projector) {
        const step = event.shiftKey ? 10 : 1;
        const dx = key === "arrowleft" ? -step : key === "arrowright" ? step : 0;
        const dy = key === "arrowup" ? -step : key === "arrowdown" ? step : 0;
        if ((dx !== 0 && lock === "y") || (dy !== 0 && lock === "x")) return;
        event.preventDefault();
        const origin = new Map<string, { x: number; y: number }>();
        for (const selectedKey of selected) {
          const item = placedByKey.get(selectedKey);
          if (item && !item.cleared) origin.set(selectedKey, { x: item.x, y: item.y });
        }
        const keys = [...origin.keys()];
        const nudge: DragState = { pointerId: -1, startX: 0, startY: 0, keys, grabbed: keys[0] ?? "", origin, moved: true };
        commitDrafts(draftsFor(nudge, dx, dy), keys);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [busy, commitDrafts, draftsFor, editor, lock, placedByKey, projector, selected, setSelected]);

  const cursor = lock === "y" ? "ns-resize" : lock === "x" ? "ew-resize" : "move";

  return (
    <div className={`point-overlay${busy ? " busy" : ""}`}>
      <svg
        ref={svgRef}
        className="point-overlay-svg"
        onPointerDown={onBackgroundDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        role="application"
        aria-label={zh ? "拖动数据点修正数据" : "Drag data points to correct values"}
      >
        {placed.map((item) => {
          if (!Number.isFinite(item.ox) || !Number.isFinite(item.oy)) return null;
          const isSelected = selected.has(item.point.key);
          const bar = item.point.set.kind === "bar";
          return (
            <g key={item.point.key} className="point-handle-group">
              {(item.moved || item.cleared) && <circle className="point-ghost" cx={item.ox} cy={item.oy} r={4} />}
              {item.moved && <line className="point-trail" x1={item.ox} y1={item.oy} x2={item.x} y2={item.y} />}
              {item.moved && bar && (
                <line
                  className="point-bar-end"
                  x1={item.point.set.orientation === "h" ? item.x : item.x - 9}
                  x2={item.point.set.orientation === "h" ? item.x : item.x + 9}
                  y1={item.point.set.orientation === "h" ? item.y - 9 : item.y}
                  y2={item.point.set.orientation === "h" ? item.y + 9 : item.y}
                />
              )}
              {item.cleared ? (
                <g className={`point-cleared${isSelected ? " selected" : ""}`} onPointerDown={(e) => onHandleDown(e, item.point.key)}>
                  <circle cx={item.ox} cy={item.oy} r={9} className="point-hit" />
                  <path d={`M${item.ox - 4},${item.oy - 4}L${item.ox + 4},${item.oy + 4}M${item.ox + 4},${item.oy - 4}L${item.ox - 4},${item.oy + 4}`} />
                  <title>{describe(item.point, drafts)}</title>
                </g>
              ) : (
                Number.isFinite(item.x) &&
                Number.isFinite(item.y) && (
                  <g onPointerDown={(e) => onHandleDown(e, item.point.key)} style={{ cursor }}>
                    <circle cx={item.x} cy={item.y} r={10} className="point-hit" />
                    <circle
                      cx={item.x}
                      cy={item.y}
                      r={bar ? 5 : 5.5}
                      className={`point-handle${isSelected ? " selected" : ""}${item.moved ? " edited" : ""}`}
                    />
                    <title>{describe(item.point, drafts)}</title>
                  </g>
                )
              )}
            </g>
          );
        })}
        {band && (
          <rect
            className="point-band"
            x={Math.min(band.x0, band.x1)}
            y={Math.min(band.y0, band.y1)}
            width={Math.abs(band.x1 - band.x0)}
            height={Math.abs(band.y1 - band.y0)}
          />
        )}
      </svg>
      {hint && (
        <div className="point-drag-hint" style={{ left: Math.min(hint.x + 14, Math.max(0, size.width - 260)), top: Math.max(4, hint.y - 34) }}>
          {hint.text}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------- panel

interface PointEditPanelProps {
  editor: PointEditorState;
  language: Language;
  busy: boolean;
  /** Save the edits as a corrected dataset version; resolves true on success. */
  onApply: (edits: CellEdit[], note: string) => Promise<boolean>;
  onClose: () => void;
}

function SelectedValueInput({
  value,
  disabled,
  onCommit,
}: {
  value: number | null;
  disabled: boolean;
  onCommit: (value: number | null) => void;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const trimmed = text.trim();
    if (trimmed === "") {
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(trimmed);
    if (Number.isFinite(parsed)) onCommit(parsed);
    else setText(value === null ? "" : String(value));
  };
  return (
    <input
      type="number"
      step="any"
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
      }}
    />
  );
}

export function PointEditPanel({ editor, language, busy, onApply, onClose }: PointEditPanelProps) {
  const zh = language === "zh";
  const [saving, setSaving] = useState(false);
  const { data, loading, error, points, pending, selected, lock, setLock } = editor;
  const disabled = busy || saving;

  const sets = data?.sets.filter((set) => set.x.editable || set.y.editable) || [];
  const ambiguous = sets.reduce((sum, set) => sum + set.ambiguous, 0);
  const columns = [...new Set(sets.flatMap((set) => [set.x, set.y].filter((spec) => spec.editable).map((spec) => spec.column as string)))];
  const selectedPoints = [...selected].map((key) => editor.pointByKey.get(key)).filter((point): point is EditablePoint => Boolean(point));
  const single = selectedPoints.length === 1 ? selectedPoints[0] : null;

  const apply = async () => {
    if (pending.length === 0) return;
    setSaving(true);
    try {
      if (await onApply(editor.edits, editor.note.trim())) editor.resetEdits();
    } finally {
      setSaving(false);
    }
  };

  const close = () => {
    if (pending.length > 0 && !window.confirm(zh ? `放弃 ${pending.length} 处尚未应用的修改？` : `Discard ${pending.length} unapplied edit(s)?`)) return;
    editor.resetEdits();
    onClose();
  };

  return (
    <div className="point-panel">
      <div className="point-panel-head">
        <strong>{zh ? "✋ 拖动数据点修正数据" : "✋ Drag points to correct data"}</strong>
        <button type="button" className="btn-icon" onClick={close} disabled={saving} title={zh ? "退出" : "Close"}>
          ✕
        </button>
      </div>

      {loading && <p className="hint">{zh ? "正在识别图中的数据点…" : "Finding the data points in the figure…"}</p>}
      {error && <div className="error-alert">{error}</div>}

      {data && !loading && (
        <>
          {points.length === 0 ? (
            <p className="hint point-empty">
              {zh
                ? "这张图里没有能对应到原始数据行的点。拖动修正只适用于直接画出原始数值的点、折线顶点和柱子（散点图、折线图、逐行的柱状图、抖动散点等）；均值柱、箱线图、直方图或经过换算（如取对数）的数值不能直接对应到某一行。"
                : "No mark in this figure maps to a data row. Dragging works for marks that plot raw values (scatter, line vertices, one-bar-per-row bar charts, strip plots); means, box plots, histograms or transformed values (e.g. log) cannot be traced to a single row."}
            </p>
          ) : (
            <p className="point-summary">
              {zh
                ? `可拖动 ${points.length} 个点（${sets.length} 组），对应列：${columns.join("、")}`
                : `${points.length} draggable point(s) in ${sets.length} group(s); columns: ${columns.join(", ")}`}
              {data.unmatched > 0 && (zh ? `；另有 ${data.unmatched} 组图形无法对应到数据行` : `; ${data.unmatched} other mark group(s) could not be traced`)}
            </p>
          )}

          {points.length > 0 && (
            <>
              <div className="point-controls">
                <div className="radio-pills">
                  {(
                    [
                      ["y", zh ? "只改竖直方向" : "Vertical only"],
                      ["x", zh ? "只改水平方向" : "Horizontal only"],
                      ["free", zh ? "自由拖动" : "Free"],
                    ] as [AxisLock, string][]
                  ).map(([value, label]) => (
                    <label key={value} className={`radio-pill ${lock === value ? "active" : ""}`}>
                      <input type="radio" checked={lock === value} onChange={() => setLock(value)} />
                      {label}
                    </label>
                  ))}
                </div>
                <div className="point-history-buttons">
                  <button type="button" className="btn secondary small" onClick={editor.undo} disabled={disabled || !editor.canUndo} title="Ctrl+Z">
                    ↶ {zh ? "撤销" : "Undo"}
                  </button>
                  <button type="button" className="btn secondary small" onClick={editor.redo} disabled={disabled || !editor.canRedo} title="Ctrl+Y">
                    ↷ {zh ? "重做" : "Redo"}
                  </button>
                </div>
              </div>

              <p className="point-tip">
                {zh
                  ? "拖动圆点修改数值；Shift/Ctrl 点击或在空白处框选可多选，一起拖动；方向键微调（Shift 加大步长）；Delete 把数值设为缺失；Esc 取消选择。"
                  : "Drag a handle to change its value; Shift/Ctrl-click or drag a box to select several and move them together; arrow keys nudge (Shift for larger steps); Delete marks values missing; Esc clears the selection."}
              </p>

              {/* Always rendered with a fixed height: the panel must not change size while a
                  point is being dragged, or the figure above it would shift under the pointer. */}
              <div className="point-selection">
                {selectedPoints.length === 0 ? (
                  <div className="point-selection-empty">{zh ? "未选择数据点：点击图上的圆点查看并精确修改数值。" : "No point selected: click a handle to inspect or type an exact value."}</div>
                ) : single ? (
                    <>
                      <div className="point-selection-title">{zh ? `第 ${single.row + 1} 行` : `Row ${single.row + 1}`}</div>
                      <div className="point-selection-fields">
                        {AXES.map((axis) => {
                          const spec = single.set[axis];
                          if (!spec.column) return null;
                          if (!spec.editable) {
                            return (
                              <span key={axis} className="point-field readonly">
                                {spec.column} = {displayValue(single.set, axis, single.index)}
                              </span>
                            );
                          }
                          return (
                            <label key={axis} className="point-field">
                              <span>{spec.column}</span>
                              <SelectedValueInput
                                value={editor.cellValue(single, axis)}
                                disabled={disabled}
                                onCommit={(value) => editor.applyChanges([{ point: single, axis, value }])}
                              />
                              <small>{zh ? `原值 ${formatValue(editor.originalValue(single, axis))}` : `was ${formatValue(editor.originalValue(single, axis), false)}`}</small>
                            </label>
                          );
                        })}
                      </div>
                    </>
                ) : (
                  <div className="point-selection-title">{zh ? `已选 ${selectedPoints.length} 个点` : `${selectedPoints.length} points selected`}</div>
                )}
                {selectedPoints.length > 0 && (
                  <div className="point-selection-actions">
                    <button type="button" className="btn secondary small" onClick={editor.clearSelected} disabled={disabled}>
                      {zh ? "设为缺失值" : "Mark missing"}
                    </button>
                    <button type="button" className="btn secondary small" onClick={editor.revertSelected} disabled={disabled}>
                      {zh ? "还原所选" : "Revert selected"}
                    </button>
                  </div>
                )}
              </div>

              {ambiguous > 0 && (
                <p className="hint">
                  {zh
                    ? `有 ${ambiguous} 个点在数据里存在取值完全相同的行，修改的是其中一行（可在修正记录里看到行号）。`
                    : `${ambiguous} point(s) have rows with identical values; one of those rows is edited (the row number is logged).`}
                </p>
              )}
            </>
          )}

          <div className="point-pending">
            <div className="point-pending-head">
              <span>{zh ? `待应用的修改（${pending.length}）` : `Pending edits (${pending.length})`}</span>
              {pending.length > 0 && (
                <button type="button" className="btn-link" onClick={() => editor.revertKeys(new Set(pending.map((edit) => cellKey(edit.row, edit.column))))} disabled={disabled}>
                  {zh ? "全部清除" : "Clear all"}
                </button>
              )}
            </div>
            <div className="point-pending-body">
              {pending.length === 0 ? (
                <div className="point-pending-empty">{zh ? "还没有修改。" : "No edits yet."}</div>
              ) : (
              <table className="point-pending-table">
                <thead>
                  <tr>
                    <th>{zh ? "行" : "Row"}</th>
                    <th>{zh ? "列" : "Column"}</th>
                    <th>{zh ? "原值 → 新值" : "Old → new"}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pending.map((edit) => (
                    <tr key={cellKey(edit.row, edit.column)}>
                      <td>{edit.row + 1}</td>
                      <td>{edit.column}</td>
                      <td>
                        {formatValue(edit.oldValue, zh)} → <strong>{formatValue(edit.newValue, zh)}</strong>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn-icon"
                          onClick={() => editor.revertKeys(new Set([cellKey(edit.row, edit.column)]))}
                          disabled={disabled}
                          title={zh ? "撤回这一处" : "Revert this edit"}
                        >
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              )}
            </div>
          </div>

          <label className="point-note">
            <span>{zh ? "修改原因（写入修正记录，可选）" : "Reason (saved in the correction log, optional)"}</span>
            <input
              value={editor.note}
              maxLength={500}
              onChange={(e) => editor.setNote(e.target.value)}
              placeholder={zh ? "例如：录入错误，按原始记录本更正" : "e.g. transcription error, corrected from the lab notebook"}
            />
          </label>

          <p className="point-integrity">
            {zh
              ? "原始数据不会被覆盖：修正会另存为新的数据集版本，并逐格记录原值和新值，可在数据工作台查看；导出项目包时附带 data_corrections.csv。"
              : "The original data is never overwritten: corrections are saved as a new dataset version with every old and new value logged (see the data workbench); project bundles include data_corrections.csv."}
          </p>

          <div className="point-panel-actions">
            <button type="button" className="btn" onClick={() => void apply()} disabled={disabled || pending.length === 0}>
              {saving ? (zh ? "正在保存并重新渲染…" : "Saving and re-rendering…") : zh ? `应用 ${pending.length} 处修改` : `Apply ${pending.length} edit(s)`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
