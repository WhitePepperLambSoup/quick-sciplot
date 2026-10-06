import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import type { PlotlyElement } from "plotly.js-dist-min";
import type { CellEdit, PlotResult } from "../types";
import { downloadExport } from "../api";
import { saveBlob } from "../utils";
import { InteractiveManipulator } from "./InteractiveManipulator";
import type { AxisRanges } from "./InteractivePlot";
import type { Language } from "./ParameterInput";
import { PointEditPanel, PointOverlay, usePointEditor } from "./PointEditor";

const LazyInteractivePlot = lazy(() => import("./InteractivePlot").then((m) => ({ default: m.InteractivePlot })));

interface PreviewCanvasProps {
  language: Language;
  result: PlotResult | null;
  busy: boolean;
  onRunCritic?: (useAi: boolean) => void;
  onOpenStatsModal?: () => void;
  onOpenComplianceModal?: () => void;
  onInteractiveAdjust?: (action: string, params: Record<string, unknown>) => Promise<void>;
  /** Save dragged data-point corrections as a new dataset version and re-render. */
  onApplyPointEdits?: (edits: CellEdit[], note: string) => Promise<boolean>;
}

const EXPORTS: { format: string; label: string; title: string; extension: string }[] = [
  { format: "png", label: "PNG", title: "PNG (300 DPI)", extension: "png" },
  { format: "svg", label: "SVG", title: "SVG (vector)", extension: "svg" },
  { format: "pdf", label: "PDF", title: "PDF (print)", extension: "pdf" },
  { format: "eps", label: "EPS", title: "EPS (PostScript)", extension: "eps" },
  { format: "plotly", label: "JSON", title: "Plotly JSON", extension: "plotly.json" },
];

function formatRange(range?: [number, number]): string {
  return range ? `${range[0].toPrecision(4)} – ${range[1].toPrecision(4)}` : "—";
}

export function PreviewCanvas({
  language,
  result,
  busy,
  onRunCritic,
  onOpenStatsModal,
  onOpenComplianceModal,
  onInteractiveAdjust,
  onApplyPointEdits,
}: PreviewCanvasProps) {
  const zh = language === "zh";
  const [manipulating, setManipulating] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [ranges, setRanges] = useState<AxisRanges>({});
  const [hlineValue, setHlineValue] = useState("");

  const isInteractive = Boolean(result?.run.success && result.run.interactive);
  const [pointMode, setPointMode] = useState(false);
  const [graph, setGraph] = useState<PlotlyElement | null>(null);
  const [layoutTick, setLayoutTick] = useState(0);
  const pointEditor = usePointEditor(result?.revision_id, pointMode && Boolean(result?.run.success));
  const canEditPoints = Boolean(onApplyPointEdits && result?.run.success && result.revision_id);

  useEffect(() => {
    if (!result?.run.success) {
      setPointMode(false);
      setManipulating(false);
    }
  }, [result]);

  const onPlotLayout = useCallback((next: PlotlyElement | null) => {
    setGraph(next);
    setLayoutTick((tick) => tick + 1);
  }, []);

  const handleDownload = async (format: string, extension: string) => {
    if (!result?.revision_id || downloadingFormat) return;
    setDownloadingFormat(format);
    setDownloadError(null);
    try {
      const blob = await downloadExport(result.revision_id, format);
      saveBlob(blob, `quick-sciplot-${result.revision_id.slice(0, 8)}.${extension}`);
    } catch (error) {
      setDownloadError(String(error));
    } finally {
      setDownloadingFormat(null);
    }
  };

  const applyRange = (axis: "x" | "y") => {
    const range = ranges[axis];
    if (!range || !onInteractiveAdjust) return;
    void onInteractiveAdjust(`${axis}lim`, { [`${axis}min`]: range[0], [`${axis}max`]: range[1] });
  };

  return (
    <section className="panel center">
      <div className="preview-heading">
        <h2>
          <span>📈</span>
          <span>{zh ? "画布预览" : "Preview Canvas"}</span>
        </h2>
        {result?.run.success && (
          <div className="preview-toolbar">
            {canEditPoints && (
              <button
                className={`btn small ${pointMode ? "primary" : "secondary"}`}
                onClick={() => {
                  setPointMode(!pointMode);
                  setManipulating(false);
                }}
                disabled={busy}
                style={pointMode ? { background: "var(--primary-600)", color: "#fff", borderColor: "var(--primary-700)" } : {}}
                title={zh ? "在图上直接拖动数据点来修正数据，图像随之更新（另存为新的数据版本，保留修改记录）" : "Drag data points on the figure to correct values (saved as a new dataset version with a log)"}
              >
                <span>✋</span>
                <span>{zh ? (pointMode ? "正在修正数据点…" : "拖动数据点") : pointMode ? "Editing points…" : "Drag points"}</span>
              </button>
            )}
            {!isInteractive && (
              <button
                className={`btn small ${manipulating ? "primary" : "secondary"}`}
                onClick={() => {
                  setManipulating(!manipulating);
                  setPointMode(false);
                }}
                disabled={busy}
                style={manipulating ? { background: "var(--primary-600)", color: "#fff", borderColor: "var(--primary-700)" } : {}}
                title={zh ? "在图表上直接拖动参考线/坐标范围，代码自动相应调整" : "Drag reference lines and limits on the figure"}
              >
                <span>🎯</span>
                <span>{zh ? (manipulating ? "正在交互修正…" : "交互式图像修正") : manipulating ? "Adjusting…" : "Interactive correction"}</span>
              </button>
            )}
            {onOpenStatsModal && !isInteractive && (
              <button className="btn secondary small" onClick={onOpenStatsModal} disabled={busy}>
                <span>⚡</span>
                <span>{zh ? "统计与回归" : "Stats & fit"}</span>
              </button>
            )}
            {onRunCritic && (
              <>
                <button className="btn secondary small" onClick={() => onRunCritic(false)} disabled={busy} title={zh ? "基于规则快速检查" : "Fast rule-based checks"}>
                  <span>🔍</span>
                  <span>{zh ? "排版体检" : "Quick critique"}</span>
                </button>
                <button
                  className="btn secondary small"
                  onClick={() => onRunCritic(true)}
                  disabled={busy}
                  title={zh ? "把渲染出的图片交给支持图像输入的模型审查（会把图片发送给模型服务）" : "Send the rendered image to a vision-capable model"}
                >
                  <span>👁️</span>
                  <span>{zh ? "AI 视觉体检" : "AI critique"}</span>
                </button>
              </>
            )}
            {onOpenComplianceModal && (
              <button className="btn secondary small" onClick={onOpenComplianceModal} disabled={busy}>
                <span>📋</span>
                <span>{zh ? "期刊合规审查" : "Journal compliance"}</span>
              </button>
            )}
          </div>
        )}
      </div>

      {isInteractive && onInteractiveAdjust && (
        <div className="plotly-toolbar">
          <span className="plotly-ranges">
            X: {formatRange(ranges.x)} · Y: {formatRange(ranges.y)}
          </span>
          <button className="btn secondary small" disabled={busy || !ranges.x} onClick={() => applyRange("x")}>
            {zh ? "当前 X 范围写入代码" : "Save X range to code"}
          </button>
          <button className="btn secondary small" disabled={busy || !ranges.y} onClick={() => applyRange("y")}>
            {zh ? "当前 Y 范围写入代码" : "Save Y range to code"}
          </button>
          <span className="plotly-hline">
            <input
              type="number"
              step="any"
              value={hlineValue}
              placeholder="y ="
              onChange={(e) => setHlineValue(e.target.value)}
            />
            <button
              className="btn secondary small"
              disabled={busy || hlineValue.trim() === "" || !Number.isFinite(Number(hlineValue))}
              onClick={() => void onInteractiveAdjust("hline", { y: Number(hlineValue), color: "red", linestyle: "--", label: "Cutoff" })}
            >
              {zh ? "添加/移动水平参考线" : "Add/move y line"}
            </button>
          </span>
        </div>
      )}

      <div className="canvas-viewport">
        {busy && (
          <div className="canvas-loading-overlay">
            <div className="loading-spinner" />
            <div className="loading-text">{zh ? "正在执行代码并渲染出版级图表…" : "Rendering publication figure…"}</div>
          </div>
        )}

        {result?.run.success && result.run.interactive ? (
          <div className="canvas-paper" style={{ width: "100%" }}>
            <Suspense fallback={<div className="loading-spinner" />}>
              <LazyInteractivePlot figure={result.run.interactive} onRangesChange={setRanges} onLayout={onPlotLayout} />
            </Suspense>
            {pointMode && graph && (
              <PointOverlay editor={pointEditor} language={language} busy={busy} graph={graph} layoutTick={layoutTick} />
            )}
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
            {pointMode && <PointOverlay editor={pointEditor} language={language} busy={busy} />}
          </div>
        ) : (
          <div className="hint" style={{ textAlign: "center", maxWidth: "340px" }}>
            <div style={{ fontSize: "36px", marginBottom: "8px" }}>📊</div>
            <p style={{ margin: "0 0 6px", fontWeight: 600, color: "#475569" }}>{zh ? "暂无生成图表" : "No Plot Rendered Yet"}</p>
            <p style={{ margin: 0, fontSize: "12px" }}>
              {zh
                ? "在右侧描述绘图意图、点击智能建议，或使用顶部的“科研图模板”。也可以直接把数据文件拖进窗口。"
                : "Describe your plot in the chat, pick a suggestion or a template. You can also drop data files onto the window."}
            </p>
          </div>
        )}
      </div>

      {pointMode && onApplyPointEdits && result?.run.success && (
        <PointEditPanel
          editor={pointEditor}
          language={language}
          busy={busy}
          onApply={onApplyPointEdits}
          onClose={() => setPointMode(false)}
        />
      )}

      {result && !result.run.success && (
        <pre className="error" style={{ marginTop: "12px" }}>
          {result.run.error_line ? (zh ? `第 ${result.run.error_line} 行出错\n` : `Error on line ${result.run.error_line}\n`) : ""}
          {result.run.stderr || (zh ? "代码执行异常" : "Execution failed")}
        </pre>
      )}

      {result?.run.success && result.revision_id && (
        <div className="export-actions">
          <span className="export-label">{zh ? "导出：" : "Export:"}</span>
          <div className="export-links">
            {EXPORTS.filter(({ format }) => result.export_formats.includes(format)).map(({ format, label, title, extension }) => (
              <button
                key={format}
                type="button"
                className="export-link"
                onClick={() => void handleDownload(format, extension)}
                disabled={Boolean(downloadingFormat)}
                title={title}
              >
                <span>{downloadingFormat === format ? "…" : "↓"}</span>
                <span>{label}</span>
              </button>
            ))}
            <button
              type="button"
              className="export-link"
              onClick={() => void handleDownload("script", "py")}
              disabled={Boolean(downloadingFormat)}
              title={zh ? "可独立运行的 Python 脚本（读取同目录 data.csv）" : "Standalone Python script (reads data.csv)"}
            >
              <span>{downloadingFormat === "script" ? "…" : "↓"}</span>
              <span>{zh ? "脚本" : "Script"}</span>
            </button>
            <button
              type="button"
              className="export-link"
              onClick={() => void handleDownload("bundle", "zip")}
              disabled={Boolean(downloadingFormat)}
              title={zh ? "数据 + 脚本 + 图片的可复现项目包" : "Reproducible bundle: data, script and figures"}
            >
              <span>{downloadingFormat === "bundle" ? "…" : "↓"}</span>
              <span>{zh ? "项目包" : "Bundle"}</span>
            </button>
          </div>
          {downloadError && <span className="error">{downloadError}</span>}
        </div>
      )}
    </section>
  );
}
