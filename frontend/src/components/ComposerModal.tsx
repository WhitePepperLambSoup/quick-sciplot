import { useState } from "react";
import { composePlots, getRevisionDetail } from "../api";
import type { DatasetInfo, PlotResult, RevisionSummary } from "../types";
import { useEscape } from "../utils";
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

type LayoutKey = "1x2" | "2x1" | "2x2" | "1+2" | "2+1" | "1x3" | "3x1";

const LAYOUT_PANEL_COUNTS: Record<LayoutKey, number> = {
  "1x2": 2,
  "2x1": 2,
  "2x2": 4,
  "1+2": 3,
  "2+1": 3,
  "1x3": 3,
  "3x1": 3,
};

const LAYOUTS: { key: LayoutKey; zh: string; en: string; cells: string[] }[] = [
  { key: "1x2", zh: "1×2 左右双图", en: "1×2 side by side", cells: ["", ""] },
  { key: "2x1", zh: "2×1 上下双图", en: "2×1 stacked", cells: ["", ""] },
  { key: "1x3", zh: "1×3 横排三图", en: "1×3 row", cells: ["", "", ""] },
  { key: "3x1", zh: "3×1 竖排三图", en: "3×1 column", cells: ["", "", ""] },
  { key: "2x2", zh: "2×2 田字四图", en: "2×2 grid", cells: ["", "", "", ""] },
  { key: "1+2", zh: "1+2 左一右二", en: "1+2 big left", cells: ["span-large", "", ""] },
  { key: "2+1", zh: "2+1 左二右一", en: "2+1 big right", cells: ["", "", "span-large-right"] },
];

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
  useEscape(onClose, !busy);

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
              {LAYOUTS.map(({ key, zh, en, cells }) => (
                <div
                  key={key}
                  className={`layout-card ${layout === key ? "active" : ""}`}
                  onClick={() => setLayout(key)}
                >
                  <div className={`layout-preview layout-${key.replace("+", "-plus-")}`}>
                    {cells.map((cell, index) => (
                      <span key={index} className={cell || undefined} />
                    ))}
                  </div>
                  <div className="layout-title">{language === "zh" ? zh : en}</div>
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
