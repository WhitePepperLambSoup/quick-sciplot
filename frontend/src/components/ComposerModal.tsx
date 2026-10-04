import { useState } from "react";
import { composePlots, getRevisionDetail } from "../api";
import type { DatasetInfo, PlotResult, RevisionSummary } from "../types";
import type { Language } from "./ParameterInput";

interface ComposerModalProps {
  language: Language;
  dataset: DatasetInfo;
  currentCode: string;
  history: RevisionSummary[];
  preset?: string;
  onClose: () => void;
  onSuccess: (result: PlotResult) => void;
}

type LayoutKey = "1x2" | "2x1" | "2x2" | "1+2";

const LAYOUT_PANEL_COUNTS: Record<LayoutKey, number> = {
  "1x2": 2,
  "2x1": 2,
  "2x2": 4,
  "1+2": 3,
};

const PANEL_TAGS = ["A", "B", "C", "D"];

export function ComposerModal({
  language,
  dataset,
  currentCode,
  history,
  preset,
  onClose,
  onSuccess,
}: ComposerModalProps) {
  const [layout, setLayout] = useState<LayoutKey>("1x2");
  const [panelTitles, setPanelTitles] = useState<string[]>(["Panel A", "Panel B", "Panel C", "Panel D"]);
  const [panelCodes, setPanelCodes] = useState<string[]>([
    currentCode,
    currentCode || "ax.scatter(df[df.columns[0]], df[df.columns[1]], alpha=0.7, color='#e74c3c')",
    "ax.hist(df[df.columns[1]], bins=15, color='#3498db', edgecolor='black')",
    "ax.boxplot(df[df.columns[1]].dropna(), vert=False)",
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slotCount = LAYOUT_PANEL_COUNTS[layout];

  const handleLoadRevision = async (index: number, revId: string) => {
    if (!revId) return;
    try {
      const detail = await getRevisionDetail(revId);
      if (detail && detail.code) {
        const copy = [...panelCodes];
        copy[index] = detail.code;
        setPanelCodes(copy);
      }
    } catch {
      // 忽略读取失败
    }
  };

  const handleCompose = async () => {
    setBusy(true);
    setError(null);
    try {
      const panels = Array.from({ length: slotCount }, (_, i) => ({
        title: panelTitles[i] || "",
        code: panelCodes[i] || "",
      }));
      const res = await composePlots({
        dataset_id: dataset.id,
        layout,
        panels,
        preset,
      });
      onSuccess(res);
      onClose();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-dialog composer-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{language === "zh" ? "📊 顶刊组合多子图编排 (Figure Composer)" : "📊 Multi-panel Figure Composer"}</h3>
          <button className="btn-icon" onClick={onClose} disabled={busy}>✕</button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">
            {language === "zh"
              ? "将多个独立子图无缝拼接为期刊标准多栏大图（Figure 1A, 1B, 1C...），自动隔离变量作用域并注入统一加粗子图标号。"
              : "Compose multiple subplots into standard publication multi-panel figures with unified styles and bold tags."}
          </p>

          <div className="form-group">
            <label>{language === "zh" ? "选择多图期刊排版网格" : "Choose Subplot Grid Layout"}</label>
            <div className="layout-picker">
              {(["1x2", "2x1", "2x2", "1+2"] as LayoutKey[]).map((key) => (
                <div
                  key={key}
                  className={`layout-card ${layout === key ? "active" : ""}`}
                  onClick={() => setLayout(key)}
                >
                  <div className={`layout-preview layout-${key.replace("+", "-plus-")}`}>
                    {key === "1x2" && <><span /> <span /></>}
                    {key === "2x1" && <><span /> <span /></>}
                    {key === "2x2" && <><span /> <span /> <span /> <span /></>}
                    {key === "1+2" && <><span className="span-large" /> <span /> <span /></>}
                  </div>
                  <div className="layout-title">
                    {key === "1x2" ? (language === "zh" ? "1×2 左右双图" : "1x2 Side-by-side") : ""}
                    {key === "2x1" ? (language === "zh" ? "2×1 上下双图" : "2x1 Stacked") : ""}
                    {key === "2x2" ? (language === "zh" ? "2×2 田字四图" : "2x2 4-Grid") : ""}
                    {key === "1+2" ? (language === "zh" ? "1+2 左一右二" : "1+2 Multi-scale") : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel-slots">
            {Array.from({ length: slotCount }, (_, i) => (
              <div key={i} className="panel-slot-card">
                <div className="slot-header">
                  <span className="panel-badge">{PANEL_TAGS[i]}</span>
                  <input
                    type="text"
                    className="slot-title-input"
                    placeholder={language === "zh" ? `子图 ${PANEL_TAGS[i]} 标题 (可选)` : `Title for Panel ${PANEL_TAGS[i]}`}
                    value={panelTitles[i]}
                    onChange={(e) => {
                      const copy = [...panelTitles];
                      copy[i] = e.target.value;
                      setPanelTitles(copy);
                    }}
                    disabled={busy}
                  />
                  {history && history.filter((h) => h.success).length > 0 && (
                    <select
                      className="slot-history-select"
                      defaultValue=""
                      onChange={(e) => {
                        void handleLoadRevision(i, e.target.value);
                        e.target.value = "";
                      }}
                      disabled={busy}
                    >
                      <option value="" disabled>
                        {language === "zh" ? "从历史导入..." : "Import..."}
                      </option>
                      {history
                        .filter((h) => h.success)
                        .map((h, hIdx) => (
                          <option key={h.id} value={h.id}>
                            {language === "zh"
                              ? `#${history.length - hIdx} (${h.operation})`
                              : `#${history.length - hIdx} (${h.operation})`}
                          </option>
                        ))}
                    </select>
                  )}
                </div>
                <textarea
                  className="slot-code-area"
                  rows={3}
                  value={panelCodes[i] || ""}
                  placeholder={language === "zh" ? `子图 ${PANEL_TAGS[i]} 的绘图代码 (ax.plot / sns.xxx)` : "Subplot Python code (ax.plot...)"}
                  onChange={(e) => {
                    const copy = [...panelCodes];
                    copy[i] = e.target.value;
                    setPanelCodes(copy);
                  }}
                  disabled={busy}
                />
              </div>
            ))}
          </div>

          {error && <div className="error-alert">{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn secondary" onClick={onClose} disabled={busy}>
            {language === "zh" ? "取消" : "Cancel"}
          </button>
          <button className="btn" onClick={handleCompose} disabled={busy}>
            {busy
              ? (language === "zh" ? "排版拼接渲染中..." : "Composing...")
              : (language === "zh" ? "拼合并渲染多子图" : "Compose & Render")}
          </button>
        </div>
      </div>
    </div>
  );
}
