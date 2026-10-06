import { useState } from "react";
import { operationInfo } from "../operations";
import type { DatasetInfo, Preset, RevisionSummary } from "../types";
import type { Language } from "./ParameterInput";

interface DataPanelProps {
  language: Language;
  dataset: DatasetInfo | null;
  datasets: DatasetInfo[];
  selectedDatasetIds: string[];
  presets: Preset[];
  selectedPreset: string;
  history: RevisionSummary[];
  activeRevisionId?: string;
  busy: boolean;
  onSelectDataset: (item: DatasetInfo) => void;
  onToggleDatasetSelect: (id: string, checked: boolean) => void;
  onCombineSelected: () => void;
  onSelectPreset: (presetId: string) => void;
  onRestoreRevision: (revision: RevisionSummary) => void;
  onDeleteDataset?: (id: string) => void;
  onOpenWorkbench?: (item: DatasetInfo) => void;
  onUpdateRevision?: (id: string, patch: { label?: string; starred?: boolean }) => void;
  onCompareRevisions?: (olderId: string, newerId: string) => void;
}

export function DataPanel({
  language,
  dataset,
  datasets,
  selectedDatasetIds,
  presets,
  selectedPreset,
  history,
  activeRevisionId,
  busy,
  onSelectDataset,
  onToggleDatasetSelect,
  onCombineSelected,
  onSelectPreset,
  onRestoreRevision,
  onDeleteDataset,
  onOpenWorkbench,
  onUpdateRevision,
  onCompareRevisions,
}: DataPanelProps) {
  const zh = language === "zh";
  const selectedPresetInfo = presets.find((p) => p.id === selectedPreset);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState("");
  const [starredOnly, setStarredOnly] = useState(false);

  const getDtypeClass = (dtype: string) => {
    if (dtype.includes("int") || dtype.includes("float")) return "dtype-num";
    if (dtype === "object" || dtype.includes("str") || dtype.includes("category")) return "dtype-cat";
    if (dtype.includes("date") || dtype.includes("time")) return "dtype-date";
    return "";
  };

  const toggleCompare = (id: string) =>
    setCompareIds((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current.slice(-1), id]));

  const startCompare = () => {
    if (compareIds.length !== 2 || !onCompareRevisions) return;
    // History is newest first: the later index is the older revision.
    const [first, second] = compareIds.map((id) => history.findIndex((rev) => rev.id === id));
    const older = first > second ? compareIds[0] : compareIds[1];
    const newer = older === compareIds[0] ? compareIds[1] : compareIds[0];
    onCompareRevisions(older, newer);
  };

  const commitLabel = (revision: RevisionSummary) => {
    setEditingId(null);
    if ((revision.label || "") !== labelDraft.trim()) onUpdateRevision?.(revision.id, { label: labelDraft.trim() });
  };

  const visibleHistory = (starredOnly ? history.filter((rev) => rev.starred) : history).slice(0, 40);

  return (
    <section className="panel left">
      <div className="panel-header">
        <h2>
          <span>📁</span>
          <span>{zh ? "数据与风格" : "Data & Style"}</span>
        </h2>
        {dataset && (
          <span className="panel-tag">
            {dataset.summary.shape.rows} {zh ? "行" : "rows"} × {dataset.summary.shape.cols} {zh ? "列" : "cols"}
          </span>
        )}
      </div>

      {datasets.length > 0 && (
        <div className="dataset-files">
          <div className="dataset-files-heading">
            <span>{zh ? "已载入数据集" : "Active Datasets"}</span>
            <span>{datasets.length}</span>
          </div>
          {datasets.map((item) => (
            <div
              key={item.id}
              className={`dataset-file-card${item.id === dataset?.id ? " active" : ""}`}
              onClick={() => onSelectDataset(item)}
              title={item.name || item.id}
            >
              <div className="dataset-file-info">
                <input
                  type="checkbox"
                  checked={selectedDatasetIds.includes(item.id)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => onToggleDatasetSelect(item.id, event.target.checked)}
                  disabled={busy}
                  title={zh ? "选中后可与其它文件多表合并" : "Select to combine with other files"}
                />
                <span className="dataset-file-name">{item.name || (zh ? "未命名文件" : "Unnamed file")}</span>
                {item.provenance && (
                  <span
                    className="dataset-corrected-badge"
                    title={
                      zh
                        ? `由“${item.provenance.root_name}”修正而来，共 ${item.provenance.edit_count} 处修改（原数据保留）。在数据工作台可查看修正记录。`
                        : `Corrected from "${item.provenance.root_name}": ${item.provenance.edit_count} edit(s); the original is kept. See the workbench for the log.`
                    }
                  >
                    ✎ {item.provenance.edit_count}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                <span className="dataset-file-badge">
                  {item.summary.shape.rows} × {item.summary.shape.cols}
                </span>
                {onOpenWorkbench && (
                  <button
                    className="btn-icon dataset-action"
                    title={zh ? "预览与处理数据（筛选、宽转长、连接）" : "Preview and transform (filter, reshape, join)"}
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      onOpenWorkbench(item);
                    }}
                  >
                    🗂️
                  </button>
                )}
                {onDeleteDataset && (
                  <button
                    className="btn-icon dataset-action"
                    title={zh ? "移除此数据集" : "Delete dataset"}
                    disabled={busy}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteDataset(item.id);
                    }}
                  >
                    ×
                  </button>
                )}
              </div>
            </div>
          ))}
          {selectedDatasetIds.length >= 2 && (
            <button className="combine-button" onClick={onCombineSelected} disabled={busy}>
              <span>🔗</span>
              <span>{zh ? `按行合并选中文件（${selectedDatasetIds.length} 个）` : `Combine selected by rows (${selectedDatasetIds.length})`}</span>
            </button>
          )}
        </div>
      )}

      <div className="preset-picker">
        <label htmlFor="preset-select">
          <span>{zh ? "期刊视觉预设" : "Figure Style Preset"}</span>
        </label>
        <select id="preset-select" value={selectedPreset} onChange={(e) => onSelectPreset(e.target.value)} disabled={busy}>
          {presets.length === 0 ? (
            <option value="default">{zh ? "默认 Matplotlib" : "Default Matplotlib"}</option>
          ) : (
            presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name}
              </option>
            ))
          )}
        </select>
        {selectedPresetInfo && (
          <>
            <p className="preset-description">{selectedPresetInfo.description}</p>
            <p className="preset-source">
              {selectedPresetInfo.local_available
                ? zh
                  ? "✓ 本地预设已启用"
                  : "✓ Local preset active"
                : zh
                ? "○ 使用内置规范兜底"
                : "○ Fallback active"}
              {selectedPresetInfo.source && ` · ${selectedPresetInfo.source}`}
            </p>
          </>
        )}
      </div>

      {!dataset ? (
        <div className="hint">
          <p>
            {zh
              ? "👈 点击右上角“导入数据”或直接把文件拖进窗口，支持 CSV / TSV / TXT / Excel / JSON。"
              : "👈 Click “Import Data” or drop files onto the window. CSV, TSV, TXT, Excel and JSON are supported."}
          </p>
        </div>
      ) : (
        <div className="summary-container">
          <table className="summary">
            <thead>
              <tr>
                <th>{zh ? "列名" : "Column"}</th>
                <th>{zh ? "类型" : "Type"}</th>
                <th>{zh ? "缺失" : "Nulls"}</th>
                <th>{zh ? "特征分布" : "Distribution"}</th>
              </tr>
            </thead>
            <tbody>
              {dataset.summary.columns.map((c) => (
                <tr key={c.name}>
                  <td className="mono" title={c.name}>{c.name}</td>
                  <td>
                    <span className={`dtype-badge ${getDtypeClass(c.dtype)}`}>{c.dtype}</span>
                  </td>
                  <td>{c.nulls > 0 ? <span style={{ color: "#ef4444" }}>{c.nulls}</span> : "0"}</td>
                  <td className="mono small">
                    {c.mean !== undefined && c.mean !== null
                      ? `μ=${typeof c.mean === "number" ? c.mean.toFixed(2) : c.mean}`
                      : c.top_values?.[0]
                      ? `${c.top_values[0].value} (${c.top_values[0].count})`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dataset && (
        <div className="history-section">
          <div className="history-heading">
            <span>{zh ? "版本历史" : "Version History"}</span>
            <span className="history-tools">
              <button
                className={`btn-icon history-filter${starredOnly ? " active" : ""}`}
                title={zh ? "只看收藏" : "Starred only"}
                onClick={() => setStarredOnly(!starredOnly)}
              >
                ★
              </button>
              <span className="history-count">{history.length}</span>
            </span>
          </div>
          {compareIds.length > 0 && (
            <div className="history-compare-bar">
              <span>{zh ? `已选 ${compareIds.length}/2 个版本` : `${compareIds.length}/2 selected`}</span>
              <button className="btn small" disabled={compareIds.length !== 2} onClick={startCompare}>
                {zh ? "对比" : "Compare"}
              </button>
              <button className="btn ghost small" onClick={() => setCompareIds([])}>
                {zh ? "清除" : "Clear"}
              </button>
            </div>
          )}
          {visibleHistory.length === 0 ? (
            <p className="hint">
              {starredOnly ? (zh ? "还没有收藏的版本。" : "No starred versions yet.") : zh ? "生成第一张图后自动记录版本。" : "Versions will appear after first plot."}
            </p>
          ) : (
            <div className="history-list">
              {visibleHistory.map((revision) => {
                const { label: opLabel, icon } = operationInfo(revision.operation, language);
                const opInfo = { icon };
                return (
                  <div
                    key={revision.id}
                    className={`history-item${revision.id === activeRevisionId ? " active" : ""}${revision.success ? "" : " failed"}`}
                  >
                    <input
                      type="checkbox"
                      className="history-compare"
                      title={zh ? "勾选两个版本进行对比" : "Select two versions to compare"}
                      checked={compareIds.includes(revision.id)}
                      onChange={() => toggleCompare(revision.id)}
                    />
                    <button
                      className="history-main"
                      disabled={busy || !revision.success}
                      onClick={() => onRestoreRevision(revision)}
                      onDoubleClick={(e) => {
                        e.preventDefault();
                        setEditingId(revision.id);
                        setLabelDraft(revision.label || "");
                      }}
                      title={
                        revision.success
                          ? zh
                            ? "单击恢复该版本，双击重命名"
                            : "Click to restore, double-click to rename"
                          : zh
                          ? "失败版本"
                          : "Failed"
                      }
                    >
                      {editingId === revision.id ? (
                        <input
                          className="history-label-input"
                          autoFocus
                          value={labelDraft}
                          maxLength={80}
                          placeholder={zh ? "版本名称" : "Version name"}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setLabelDraft(e.target.value)}
                          onBlur={() => commitLabel(revision)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") commitLabel(revision);
                            if (e.key === "Escape") setEditingId(null);
                          }}
                        />
                      ) : (
                        <span className="history-item-op">
                          <span>{opInfo.icon}</span>
                          <span>{revision.label || opLabel}</span>
                        </span>
                      )}
                      <span className="history-item-time">{revision.created_at.split(" ")[1] || revision.created_at}</span>
                    </button>
                    {onUpdateRevision && (
                      <button
                        className={`btn-icon history-star${revision.starred ? " starred" : ""}`}
                        title={zh ? (revision.starred ? "取消收藏" : "收藏（不会被自动清理）") : revision.starred ? "Unstar" : "Star (kept from cleanup)"}
                        onClick={() => onUpdateRevision(revision.id, { starred: !revision.starred })}
                      >
                        {revision.starred ? "★" : "☆"}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
