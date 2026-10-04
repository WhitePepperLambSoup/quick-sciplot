import { lazy, Suspense, useState } from "react";
import type { PlotResult } from "../types";
import { downloadExport } from "../api";
import { InteractiveManipulator } from "./InteractiveManipulator";
import type { Language } from "./ParameterInput";

const LazyInteractivePlot = lazy(() => import("./InteractivePlot").then((m) => ({ default: m.InteractivePlot })));

interface PreviewCanvasProps {
  language: Language;
  result: PlotResult | null;
  busy: boolean;
  onRunCritic?: () => void;
  onOpenStatsModal?: () => void;
  onOpenComplianceModal?: () => void;
  onInteractiveAdjust?: (action: string, params: Record<string, unknown>) => Promise<void>;
}

export function PreviewCanvas({
  language,
  result,
  busy,
  onRunCritic,
  onOpenStatsModal,
  onOpenComplianceModal,
  onInteractiveAdjust,
}: PreviewCanvasProps) {
  const [manipulating, setManipulating] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const handleDownload = async (format: string) => {
    if (!result?.revision_id || downloadingFormat) return;
    setDownloadingFormat(format);
    setDownloadError(null);
    try {
      const blob = await downloadExport(result.revision_id, format);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `quick-sciplot-${result.revision_id.slice(0, 8)}.${format === "plotly" ? "plotly.json" : format}`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setDownloadError(String(error));
    } finally {
      setDownloadingFormat(null);
    }
  };

  return (
    <section className="panel center">
      <div className="preview-heading">
        <h2>
          <span>📈</span>
          <span>{language === "zh" ? "画布预览" : "Preview Canvas"}</span>
        </h2>
        {result?.run.success && (
          <div className="preview-toolbar">
            <button
              className={`btn small ${manipulating ? "primary" : "secondary"}`}
              onClick={() => setManipulating(!manipulating)}
              disabled={busy}
              style={manipulating ? { background: "var(--primary-600)", color: "#fff", borderColor: "var(--primary-700)" } : {}}
              title="在图表上直接拖动参考线/坐标范围，代码自动相应调整"
            >
              <span>🎯</span>
              <span>
                {language === "zh"
                  ? manipulating
                    ? "正在交互修正…"
                    : "交互式图像修正"
                  : manipulating
                  ? "Adjusting..."
                  : "Interactive Correction"}
              </span>
            </button>
            {onOpenStatsModal && (
              <button
                className="btn secondary small"
                onClick={onOpenStatsModal}
                disabled={busy}
                title="计算组间差异显著性并绘制标尺与星号"
              >
                <span>⚡</span>
                <span>{language === "zh" ? "标注统计显著性" : "Add Stat Brackets"}</span>
              </button>
            )}
            {onRunCritic && (
              <button
                className="btn secondary small"
                onClick={onRunCritic}
                disabled={busy}
                title="检测重叠文字、分辨率、对比度与排版问题"
              >
                <span>🔍</span>
                <span>{language === "zh" ? "排版体检" : "Visual Critic"}</span>
              </button>
            )}
            {onOpenComplianceModal && (
              <button
                className="btn secondary small"
                onClick={onOpenComplianceModal}
                disabled={busy}
                title="检查 Nature / IEEE / Cell 期刊投稿排版规范"
              >
                <span>📋</span>
                <span>{language === "zh" ? "期刊合规审查" : "Journal Compliance"}</span>
              </button>
            )}
          </div>
        )}
      </div>

      <div className="canvas-viewport">
        {busy && (
          <div className="canvas-loading-overlay">
            <div className="loading-spinner" />
            <div className="loading-text">
              {language === "zh" ? "正在执行代码并渲染出版级图表…" : "Rendering publication figure…"}
            </div>
          </div>
        )}

        {result?.run.success && result.run.interactive ? (
          <div className="canvas-paper" style={{ width: "100%" }}>
            <Suspense fallback={<div className="loading-spinner" />}>
              <LazyInteractivePlot figure={result.run.interactive} />
            </Suspense>
          </div>
        ) : result?.run.success && result.run.image ? (
          <div className="canvas-paper" style={{ position: "relative" }}>
            <img className="plot-img" src={result.run.image} alt="Generated scientific figure" />
            {manipulating && (
              <InteractiveManipulator
                language={language}
                meta={result.meta}
                inspected={result.inspected}
                busy={busy}
                onAdjust={async (action, params) => {
                  if (onInteractiveAdjust) {
                    await onInteractiveAdjust(action, params);
                  }
                }}
                onClose={() => setManipulating(false)}
              />
            )}
          </div>
        ) : (
          <div className="hint" style={{ textAlign: "center", maxWidth: "340px" }}>
            <div style={{ fontSize: "36px", marginBottom: "8px" }}>📊</div>
            <p style={{ margin: "0 0 6px", fontWeight: 600, color: "#475569" }}>
              {language === "zh" ? "暂无生成图表" : "No Plot Rendered Yet"}
            </p>
            <p style={{ margin: 0, fontSize: "12px" }}>
              {language === "zh"
                ? "在右侧描述您的绘图意图，或点击智能建议，出版级图表将在此实时呈现。"
                : "Describe your plotting goal in the chat or choose a recommendation."}
            </p>
          </div>
        )}
      </div>

      {result && !result.run.success && (
        <pre className="error" style={{ marginTop: "12px" }}>
          {result.run.stderr || (language === "zh" ? "代码执行异常" : "Execution failed")}
        </pre>
      )}

      {result?.run.success && result.revision_id && (
        <div className="export-actions">
          <span className="export-label">
            {language === "zh" ? "导出出版级文件 (300 DPI / 矢量)：" : "Export Publication Assets:"}
          </span>
          <div className="export-links">
            {(["png", "svg", "pdf", "eps", "plotly"] as const)
              .filter((format) => result.export_formats.includes(format))
              .map((format) => {
                const labels: Record<string, string> = {
                  png: "PNG (Raster 300DPI)",
                  svg: "SVG (Vector)",
                  pdf: "PDF (Print)",
                  eps: "EPS (PostScript)",
                  plotly: "JSON (Interactive)",
                };
                return (
                  <button
                    key={format}
                    type="button"
                    className="export-link"
                    onClick={() => void handleDownload(format)}
                    disabled={Boolean(downloadingFormat)}
                    title={`下载 ${labels[format]}`}
                  >
                    <span>{downloadingFormat === format ? "…" : "↓"}</span>
                    <span>{format === "plotly" ? "JSON" : format.toUpperCase()}</span>
                  </button>
                );
              })}
          </div>
          {downloadError && <span className="error">{downloadError}</span>}
        </div>
      )}
    </section>
  );
}
