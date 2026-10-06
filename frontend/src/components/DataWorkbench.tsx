import { useEffect, useMemo, useState } from "react";
import { joinDatasets, previewDataset, transformDataset } from "../api";
import type { DatasetInfo, DatasetPreview, TransformOperation } from "../types";
import { useEscape } from "../utils";
import type { Language } from "./ParameterInput";

interface DataWorkbenchProps {
  language: Language;
  dataset: DatasetInfo;
  datasets: DatasetInfo[];
  onClose: () => void;
  onCreated: (dataset: DatasetInfo) => void;
}

type Tab = "preview" | "transform" | "join";
const PAGE_SIZE = 100;

const OPERATORS: { value: string; zh: string; en: string; needsValue: boolean }[] = [
  { value: "==", zh: "等于", en: "equals", needsValue: true },
  { value: "!=", zh: "不等于", en: "not equal", needsValue: true },
  { value: ">", zh: "大于", en: ">", needsValue: true },
  { value: ">=", zh: "大于等于", en: "≥", needsValue: true },
  { value: "<", zh: "小于", en: "<", needsValue: true },
  { value: "<=", zh: "小于等于", en: "≤", needsValue: true },
  { value: "contains", zh: "包含文本", en: "contains", needsValue: true },
  { value: "not_contains", zh: "不包含文本", en: "does not contain", needsValue: true },
  { value: "notnull", zh: "非空", en: "is not empty", needsValue: false },
  { value: "isnull", zh: "为空", en: "is empty", needsValue: false },
];

function columnNames(dataset: DatasetInfo): string[] {
  return dataset.summary.columns.map((column) => column.name);
}

/** Columns available after applying ``operations`` (mirrors the backend). */
function columnsAfter(initial: string[], operations: TransformOperation[]): string[] {
  let columns = initial;
  for (const op of operations) {
    if (op.op === "select") columns = (op.columns as string[]) || columns;
    if (op.op === "melt") {
      const ids = (op.id_vars as string[]) || [];
      columns = [...ids, String(op.var_name || "variable"), String(op.value_name || "value")];
    }
  }
  return columns;
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toPrecision(6).replace(/\.?0+$/, "");
  return String(value);
}

function ColumnChecklist({
  columns,
  selected,
  onChange,
}: {
  columns: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <div className="column-checklist">
      {columns.map((column) => (
        <label key={column} className={`column-chip ${selected.includes(column) ? "active" : ""}`}>
          <input
            type="checkbox"
            checked={selected.includes(column)}
            onChange={(e) => onChange(e.target.checked ? [...selected, column] : selected.filter((c) => c !== column))}
          />
          {column}
        </label>
      ))}
    </div>
  );
}

export function DataWorkbench({ language, dataset, datasets, onClose, onCreated }: DataWorkbenchProps) {
  const zh = language === "zh";
  const [tab, setTab] = useState<Tab>("preview");
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [operations, setOperations] = useState<TransformOperation[]>([]);
  const [newName, setNewName] = useState("");
  const others = datasets.filter((item) => item.id !== dataset.id);
  const [rightId, setRightId] = useState(others[0]?.id || "");
  const [keyPairs, setKeyPairs] = useState<[string, string][]>([["", ""]]);
  const [how, setHow] = useState("inner");
  useEscape(onClose, !busy);

  const baseColumns = useMemo(() => columnNames(dataset), [dataset]);
  const rightDataset = others.find((item) => item.id === rightId);
  const rightColumns = rightDataset ? columnNames(rightDataset) : [];

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    previewDataset(dataset.id, offset, PAGE_SIZE)
      .then((data) => active && setPreview(data))
      .catch((err) => active && setError(String(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [dataset.id, offset]);

  useEffect(() => {
    // Default the join keys to columns that exist on both sides.
    const shared = baseColumns.find((column) => rightColumns.includes(column)) || "";
    setKeyPairs([[shared || baseColumns[0] || "", shared || rightColumns[0] || ""]]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rightId]);

  const updateOp = (index: number, patch: Record<string, unknown>) =>
    setOperations((ops) => ops.map((op, i) => (i === index ? ({ ...op, ...patch } as TransformOperation) : op)));

  const addOp = (kind: string) => {
    const columns = columnsAfter(baseColumns, operations);
    const defaults: Record<string, TransformOperation> = {
      filter: { op: "filter", column: columns[0] || "", operator: "==", value: "" },
      melt: { op: "melt", id_vars: columns.slice(0, 1), value_vars: [], var_name: "variable", value_name: "value" },
      select: { op: "select", columns: [...columns] },
      dropna: { op: "dropna", columns: [] },
      sort: { op: "sort", column: columns[0] || "", ascending: true },
    };
    setOperations((ops) => [...ops, defaults[kind]]);
  };

  const submit = async (action: () => Promise<DatasetInfo>) => {
    setBusy(true);
    setError(null);
    try {
      onCreated(await action());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const applyTransform = () =>
    submit(() => {
      const cleaned = operations.map((op) => {
        if (op.op === "melt" && Array.isArray(op.value_vars) && op.value_vars.length === 0) {
          const rest: Record<string, unknown> = { ...op };
          delete rest.value_vars;
          return rest as TransformOperation;
        }
        if (op.op === "dropna" && Array.isArray(op.columns) && op.columns.length === 0) {
          return { op: "dropna" } as TransformOperation;
        }
        return op;
      });
      return transformDataset(dataset.id, cleaned, newName.trim() || undefined);
    });

  const applyJoin = () =>
    submit(() =>
      joinDatasets({
        left_id: dataset.id,
        right_id: rightId,
        left_on: keyPairs.map(([left]) => left),
        right_on: keyPairs.map(([, right]) => right),
        how,
        name: newName.trim() || undefined,
      }),
    );

  const opLabels: Record<string, string> = zh
    ? { filter: "筛选行", melt: "宽表转长表", select: "选择列", dropna: "删除缺失值", sort: "排序" }
    : { filter: "Filter rows", melt: "Wide → long", select: "Select columns", dropna: "Drop missing", sort: "Sort" };

  return (
    <div className="modal-backdrop" onClick={() => !busy && onClose()}>
      <div className="modal-dialog data-workbench" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{zh ? `🗂️ 数据工作台 · ${dataset.name || "未命名"}` : `🗂️ Data workbench · ${dataset.name || "Unnamed"}`}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="journal-tabs">
          {(["preview", "transform", "join"] as Tab[]).map((key) => (
            <button key={key} type="button" className={`journal-tab ${tab === key ? "active" : ""}`} onClick={() => setTab(key)}>
              {key === "preview" && (zh ? "数据预览" : "Preview")}
              {key === "transform" && (zh ? "数据处理" : "Transform")}
              {key === "join" && (zh ? "按键连接" : "Join")}
            </button>
          ))}
        </div>

        <div className="modal-body">
          {tab === "preview" && (
            <div className="preview-pane">
              <div className="preview-meta">
                {preview
                  ? zh
                    ? `共 ${preview.total_rows} 行 × ${preview.columns.length} 列，显示第 ${preview.offset + 1}–${preview.offset + preview.rows.length} 行`
                    : `${preview.total_rows} rows × ${preview.columns.length} columns, showing ${preview.offset + 1}–${preview.offset + preview.rows.length}`
                  : ""}
                <span className="preview-pager">
                  <button className="btn secondary small" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>‹</button>
                  <button
                    className="btn secondary small"
                    disabled={loading || !preview || offset + PAGE_SIZE >= preview.total_rows}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    ›
                  </button>
                </span>
              </div>
              <div className="preview-table-wrap">
                {loading && <div className="loading-spinner" />}
                {preview && (
                  <table className="preview-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        {preview.columns.map((column) => (
                          <th key={column} title={preview.dtypes[column]}>
                            {column}
                            <small>{preview.dtypes[column]}</small>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {preview.rows.map((row, index) => (
                        <tr key={preview.offset + index}>
                          <td className="row-index">{preview.offset + index + 1}</td>
                          {preview.columns.map((column) => (
                            <td key={column} className={row[column] === null ? "cell-null" : ""}>
                              {row[column] === null ? "—" : formatCell(row[column])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {tab === "transform" && (
            <div className="transform-pane">
              <p className="modal-desc">
                {zh ? "按顺序执行下面的步骤，结果保存为新的数据集，原数据不变。" : "Steps run in order; the result is saved as a new dataset and the original is kept."}
              </p>
              {operations.map((op, index) => {
                const columns = columnsAfter(baseColumns, operations.slice(0, index));
                const operator = OPERATORS.find((item) => item.value === op.operator);
                return (
                  <div key={index} className="transform-step">
                    <div className="transform-step-head">
                      <strong>
                        {index + 1}. {opLabels[op.op]}
                      </strong>
                      <button className="btn-icon" onClick={() => setOperations((ops) => ops.filter((_, i) => i !== index))}>✕</button>
                    </div>
                    {op.op === "filter" && (
                      <div className="form-row">
                        <select value={String(op.column)} onChange={(e) => updateOp(index, { column: e.target.value })}>
                          {columns.map((column) => <option key={column}>{column}</option>)}
                        </select>
                        <select value={String(op.operator)} onChange={(e) => updateOp(index, { operator: e.target.value })}>
                          {OPERATORS.map((item) => (
                            <option key={item.value} value={item.value}>{zh ? item.zh : item.en}</option>
                          ))}
                        </select>
                        {operator?.needsValue && (
                          <input value={String(op.value ?? "")} placeholder={zh ? "值" : "value"} onChange={(e) => updateOp(index, { value: e.target.value })} />
                        )}
                      </div>
                    )}
                    {op.op === "melt" && (
                      <>
                        <label className="transform-label">{zh ? "保留为标识的列 (id_vars)" : "Identifier columns (id_vars)"}</label>
                        <ColumnChecklist columns={columns} selected={(op.id_vars as string[]) || []} onChange={(next) => updateOp(index, { id_vars: next })} />
                        <label className="transform-label">{zh ? "要展开的列（不选=其余全部）" : "Columns to unpivot (none = all others)"}</label>
                        <ColumnChecklist
                          columns={columns.filter((c) => !((op.id_vars as string[]) || []).includes(c))}
                          selected={(op.value_vars as string[]) || []}
                          onChange={(next) => updateOp(index, { value_vars: next })}
                        />
                        <div className="form-row">
                          <input value={String(op.var_name)} onChange={(e) => updateOp(index, { var_name: e.target.value })} placeholder="variable" />
                          <input value={String(op.value_name)} onChange={(e) => updateOp(index, { value_name: e.target.value })} placeholder="value" />
                        </div>
                      </>
                    )}
                    {op.op === "select" && (
                      <ColumnChecklist columns={columns} selected={(op.columns as string[]) || []} onChange={(next) => updateOp(index, { columns: next })} />
                    )}
                    {op.op === "dropna" && (
                      <>
                        <label className="transform-label">{zh ? "检查这些列（不选=任意列有缺失即删除）" : "Columns to check (none = any column)"}</label>
                        <ColumnChecklist columns={columns} selected={(op.columns as string[]) || []} onChange={(next) => updateOp(index, { columns: next })} />
                      </>
                    )}
                    {op.op === "sort" && (
                      <div className="form-row">
                        <select value={String(op.column)} onChange={(e) => updateOp(index, { column: e.target.value })}>
                          {columns.map((column) => <option key={column}>{column}</option>)}
                        </select>
                        <select value={op.ascending ? "asc" : "desc"} onChange={(e) => updateOp(index, { ascending: e.target.value === "asc" })}>
                          <option value="asc">{zh ? "升序" : "Ascending"}</option>
                          <option value="desc">{zh ? "降序" : "Descending"}</option>
                        </select>
                      </div>
                    )}
                  </div>
                );
              })}
              <div className="transform-add">
                {Object.keys(opLabels).map((kind) => (
                  <button key={kind} type="button" className="btn secondary small" onClick={() => addOp(kind)} disabled={busy}>
                    + {opLabels[kind]}
                  </button>
                ))}
              </div>
            </div>
          )}

          {tab === "join" && (
            <div className="join-pane">
              {others.length === 0 ? (
                <p className="hint">{zh ? "需要先导入另一个数据集。" : "Import another dataset first."}</p>
              ) : (
                <>
                  <div className="form-group">
                    <label>{zh ? "与哪个数据集连接" : "Join with"}</label>
                    <select value={rightId} onChange={(e) => setRightId(e.target.value)}>
                      {others.map((item) => (
                        <option key={item.id} value={item.id}>{item.name || item.id}</option>
                      ))}
                    </select>
                  </div>
                  <label className="transform-label">{zh ? "连接键（左列 = 右列）" : "Keys (left column = right column)"}</label>
                  {keyPairs.map(([left, right], index) => (
                    <div key={index} className="form-row">
                      <select value={left} onChange={(e) => setKeyPairs((pairs) => pairs.map((p, i) => (i === index ? [e.target.value, p[1]] : p)))}>
                        {baseColumns.map((column) => <option key={column}>{column}</option>)}
                      </select>
                      <span className="join-equals">=</span>
                      <select value={right} onChange={(e) => setKeyPairs((pairs) => pairs.map((p, i) => (i === index ? [p[0], e.target.value] : p)))}>
                        {rightColumns.map((column) => <option key={column}>{column}</option>)}
                      </select>
                      {keyPairs.length > 1 && (
                        <button className="btn-icon" onClick={() => setKeyPairs((pairs) => pairs.filter((_, i) => i !== index))}>✕</button>
                      )}
                    </div>
                  ))}
                  <button className="btn secondary small" type="button" onClick={() => setKeyPairs((pairs) => [...pairs, [baseColumns[0] || "", rightColumns[0] || ""]])}>
                    + {zh ? "增加连接键" : "Add key"}
                  </button>
                  <div className="radio-pills join-how">
                    {[
                      ["inner", zh ? "内连接（两边都有）" : "Inner"],
                      ["left", zh ? "左连接（保留左表）" : "Left"],
                      ["right", zh ? "右连接（保留右表）" : "Right"],
                      ["outer", zh ? "全连接" : "Outer"],
                    ].map(([value, label]) => (
                      <label key={value} className={`radio-pill ${how === value ? "active" : ""}`}>
                        <input type="radio" checked={how === value} onChange={() => setHow(value)} />
                        {label}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab !== "preview" && (
            <div className="form-group">
              <label>{zh ? "新数据集名称（可选）" : "New dataset name (optional)"}</label>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={200} />
            </div>
          )}

          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>{zh ? "关闭" : "Close"}</button>
          {tab === "transform" && (
            <button className="btn" onClick={applyTransform} disabled={busy || operations.length === 0}>
              {busy ? (zh ? "处理中…" : "Working…") : zh ? "生成新数据集" : "Create dataset"}
            </button>
          )}
          {tab === "join" && others.length > 0 && (
            <button className="btn" onClick={applyJoin} disabled={busy || !rightId || keyPairs.some(([l, r]) => !l || !r)}>
              {busy ? (zh ? "连接中…" : "Joining…") : zh ? "连接并生成新数据集" : "Join"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
