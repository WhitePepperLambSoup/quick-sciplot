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
}

const OPERATION_LABELS: Record<string, { zh: string; en: string; icon: string }> = {
  generate: { zh: "初始生成", en: "Generated", icon: "✨" },
  edit: { zh: "对话调整", en: "Edited", icon: "💬" },
  parameter: { zh: "参数微调", en: "Param Tweak", icon: "⚙️" },
  run: { zh: "代码重跑", en: "Code Run", icon: "▶️" },
  restore: { zh: "版本恢复", en: "Restored", icon: "⏪" },
  stats: { zh: "统计标注", en: "Stat Brackets", icon: "⚡" },
  compose: { zh: "多图拼版", en: "Composed", icon: "📊" },
  mimic: { zh: "论文图复刻", en: "Mimic", icon: "🎨" },
  interactive: { zh: "交互修正", en: "Interactive Fix", icon: "🎯" },
};

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
}: DataPanelProps) {
  const selectedPresetInfo = presets.find((p) => p.id === selectedPreset);

  const getDtypeClass = (dtype: string) => {
    if (dtype.includes("int") || dtype.includes("float")) return "dtype-num";
    if (dtype === "object" || dtype.includes("str") || dtype.includes("category")) return "dtype-cat";
    if (dtype.includes("date") || dtype.includes("time")) return "dtype-date";
    return "";
  };

  return (
    <section className="panel left">
      <div className="panel-header">
        <h2>
          <span>📁</span>
          <span>{language === "zh" ? "数据与风格" : "Data & Style"}</span>
        </h2>
        {dataset && (
          <span className="panel-tag">
            {dataset.summary.shape.rows} {language === "zh" ? "行" : "rows"} × {dataset.summary.shape.cols} {language === "zh" ? "列" : "cols"}
          </span>
        )}
      </div>

      {datasets.length > 0 && (
        <div className="dataset-files">
          <div className="dataset-files-heading">
            <span>{language === "zh" ? "已载入数据集" : "Active Datasets"}</span>
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
                  title="选中后可与其它文件多表合并"
                />
                <span className="dataset-file-name">{item.name || (language === "zh" ? "未命名文件" : "Unnamed file")}</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <span className="dataset-file-badge">
                  {item.summary.shape.rows} × {item.summary.shape.cols}
                </span>
                {onDeleteDataset && (
                  <button
                    className="btn-icon"
                    style={{ fontSize: "14px", padding: "1px 4px", color: "var(--text-muted)", lineHeight: 1 }}
                    title={language === "zh" ? "移除此数据集" : "Delete dataset"}
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
            <button
              className="combine-button"
              onClick={onCombineSelected}
              disabled={busy}
            >
              <span>🔗</span>
              <span>
                {language === "zh"
                  ? `合并选中文件（${selectedDatasetIds.length} 个）`
                  : `Combine Selected (${selectedDatasetIds.length})`}
              </span>
            </button>
          )}
        </div>
      )}

      <div className="preset-picker">
        <label htmlFor="preset-select">
          <span>{language === "zh" ? "期刊视觉预设" : "Figure Style Preset"}</span>
        </label>
        <select
          id="preset-select"
          value={selectedPreset}
          onChange={(e) => onSelectPreset(e.target.value)}
          disabled={busy}
        >
          {presets.length === 0 ? (
            <option value="default">{language === "zh" ? "默认 Matplotlib" : "Default Matplotlib"}</option>
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
                ? language === "zh"
                  ? "✓ 本地预设已启用"
                  : "✓ Local preset active"
                : language === "zh"
                ? "○ 使用内置规范兜底"
                : "○ Fallback active"}
              {selectedPresetInfo.source && ` · ${selectedPresetInfo.source}`}
            </p>
          </>
        )}
      </div>

      {!dataset ? (
        <div className="hint">
          <p>{language === "zh" ? "👈 点击右上角“导入数据”，支持 CSV / Excel / JSON 文件。" : "👈 Click “Import Data” on the top right. CSV, Excel, and JSON are supported."}</p>
        </div>
      ) : (
        <div className="summary-container">
          <table className="summary">
            <thead>
              <tr>
                <th>{language === "zh" ? "列名" : "Column"}</th>
                <th>{language === "zh" ? "类型" : "Type"}</th>
                <th>{language === "zh" ? "缺失" : "Nulls"}</th>
                <th>{language === "zh" ? "特征分布" : "Distribution"}</th>
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
                    {c.mean !== undefined
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
            <span>{language === "zh" ? "版本历史" : "Version History"}</span>
            <span className="history-count">{history.length}</span>
          </div>
          {history.length === 0 ? (
            <p className="hint">
              {language === "zh" ? "生成第一张图后自动记录版本。" : "Versions will appear after first plot."}
            </p>
          ) : (
            <div className="history-list">
              {history.slice(0, 15).map((revision) => {
                const opInfo = OPERATION_LABELS[revision.operation] || {
                  zh: revision.operation,
                  en: revision.operation,
                  icon: "📌",
                };
                const opLabel = opInfo[language] || revision.operation;
                return (
                  <button
                    key={revision.id}
                    className={`history-item${revision.id === activeRevisionId ? " active" : ""}`}
                    disabled={busy || !revision.success}
                    onClick={() => onRestoreRevision(revision)}
                    title={revision.success ? (language === "zh" ? "点击恢复该版本" : "Click to restore") : (language === "zh" ? "失败版本" : "Failed")}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span>{opInfo.icon}</span>
                      <span className="history-item-op">{opLabel}</span>
                    </div>
                    <span className="history-item-preset">{revision.preset}</span>
                    <span className="history-item-time">{revision.created_at.split(" ")[1] || revision.created_at}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
