import { useState, useRef, useEffect, useCallback } from "react";
import type { PlotMeta, InspectedElements } from "../types";
import type { Language } from "./ParameterInput";

interface InteractiveManipulatorProps {
  language: Language;
  meta?: PlotMeta;
  inspected?: InspectedElements;
  busy: boolean;
  onAdjust: (action: string, params: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}

type ActiveTool = "hline" | "vline" | "ylim" | "xlim";
type DragTarget = "hline" | "vline" | "ylim-top" | "ylim-bottom" | "xlim-left" | "xlim-right";

export function InteractiveManipulator({
  language,
  meta,
  inspected,
  busy,
  onAdjust,
  onClose,
}: InteractiveManipulatorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 600, height: 450 });
  const [activeTool, setActiveTool] = useState<ActiveTool>("hline");

  // 数据坐标系范围与默认值
  const xlim = meta?.xlim || [0, 10];
  const ylim = meta?.ylim || [0, 50];

  // 默认水平线与垂直线状态 (若代码中已有则提取，否则默认在 50% 处)
  const initialHline = inspected?.hlines?.[0] ?? (ylim[0] + (ylim[1] - ylim[0]) * 0.5);
  const initialVline = inspected?.vlines?.[0] ?? (xlim[0] + (xlim[1] - xlim[0]) * 0.5);

  const [currentHlineY, setCurrentHlineY] = useState<number>(initialHline);
  const [currentVlineX, setCurrentVlineX] = useState<number>(initialVline);
  const [currentYlim, setCurrentYlim] = useState<[number, number]>(ylim);
  const [currentXlim, setCurrentXlim] = useState<[number, number]>(xlim);

  // 拖拽中的临时交互状态
  const [draggingTarget, setDraggingTarget] = useState<DragTarget | null>(null);
  const [dragValueLabel, setDragValueLabel] = useState<string>("");

  // 监听容器实际尺寸
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const updateSize = () => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        setDimensions({ width: rect.width, height: rect.height });
      }
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // 同步外部变化
  useEffect(() => {
    if (inspected?.hlines?.[0] !== undefined) {
      setCurrentHlineY(inspected.hlines[0]);
    }
  }, [inspected?.hlines]);

  useEffect(() => {
    if (inspected?.vlines?.[0] !== undefined) {
      setCurrentVlineX(inspected.vlines[0]);
    }
  }, [inspected?.vlines]);

  useEffect(() => {
    if (meta?.ylim) {
      setCurrentYlim(meta.ylim);
    }
  }, [meta?.ylim]);

  useEffect(() => {
    if (meta?.xlim) {
      setCurrentXlim(meta.xlim);
    }
  }, [meta?.xlim]);

  // 计算 Matplotlib 轴区在当前容器中的绝对像素几何 [plotLeft, plotTop, plotWidth, plotHeight]
  const bbox = meta?.bbox || [0.125, 0.11, 0.775, 0.77]; // [left, bottom, width, height]
  const plotLeft = dimensions.width * bbox[0];
  const plotWidth = dimensions.width * bbox[2];
  const plotTop = dimensions.height * (1 - bbox[1] - bbox[3]);
  const plotHeight = dimensions.height * bbox[3];
  const plotRight = plotLeft + plotWidth;
  const plotBottom = plotTop + plotHeight;

  // 数据坐标 <-> 像素坐标 映射函数
  const yDataToPixel = useCallback(
    (y: number) => {
      const span = currentYlim[1] - currentYlim[0] || 1e-4;
      return plotTop + ((currentYlim[1] - y) / span) * plotHeight;
    },
    [currentYlim, plotTop, plotHeight]
  );

  const yPixelToData = useCallback(
    (py: number) => {
      const span = currentYlim[1] - currentYlim[0] || 1e-4;
      return currentYlim[1] - ((py - plotTop) / plotHeight) * span;
    },
    [currentYlim, plotTop, plotHeight]
  );

  const xDataToPixel = useCallback(
    (x: number) => {
      const span = currentXlim[1] - currentXlim[0] || 1e-4;
      return plotLeft + ((x - currentXlim[0]) / span) * plotWidth;
    },
    [currentXlim, plotLeft, plotWidth]
  );

  const xPixelToData = useCallback(
    (px: number) => {
      const span = currentXlim[1] - currentXlim[0] || 1e-4;
      return currentXlim[0] + ((px - plotLeft) / plotWidth) * span;
    },
    [currentXlim, plotLeft, plotWidth]
  );

  // 鼠标拖动处理
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingTarget) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;

    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;

    if (draggingTarget === "hline") {
      const clampedPy = Math.max(plotTop, Math.min(plotBottom, py));
      const val = yPixelToData(clampedPy);
      const rounded = Number(val.toFixed(2));
      setCurrentHlineY(rounded);
      setDragValueLabel(`Cutoff: y = ${rounded}`);
    } else if (draggingTarget === "vline") {
      const clampedPx = Math.max(plotLeft, Math.min(plotRight, px));
      const val = xPixelToData(clampedPx);
      const rounded = Number(val.toFixed(2));
      setCurrentVlineX(rounded);
      setDragValueLabel(`Marker: x = ${rounded}`);
    } else if (draggingTarget === "ylim-top") {
      const val = yPixelToData(py);
      if (val > currentYlim[0] + 0.1) {
        const rounded = Number(val.toFixed(2));
        setCurrentYlim([currentYlim[0], rounded]);
        setDragValueLabel(`Y-Max = ${rounded}`);
      }
    } else if (draggingTarget === "ylim-bottom") {
      const val = yPixelToData(py);
      if (val < currentYlim[1] - 0.1) {
        const rounded = Number(val.toFixed(2));
        setCurrentYlim([rounded, currentYlim[1]]);
        setDragValueLabel(`Y-Min = ${rounded}`);
      }
    } else if (draggingTarget === "xlim-left") {
      const val = xPixelToData(px);
      if (val < currentXlim[1] - 1e-6) {
        const rounded = Number(val.toFixed(3));
        setCurrentXlim([rounded, currentXlim[1]]);
        setDragValueLabel(`X-Min = ${rounded}`);
      }
    } else if (draggingTarget === "xlim-right") {
      const val = xPixelToData(px);
      if (val > currentXlim[0] + 1e-6) {
        const rounded = Number(val.toFixed(3));
        setCurrentXlim([currentXlim[0], rounded]);
        setDragValueLabel(`X-Max = ${rounded}`);
      }
    }
  };

  const handlePointerUp = async () => {
    if (!draggingTarget) return;
    const target = draggingTarget;
    setDraggingTarget(null);
    setDragValueLabel("");

    if (target === "hline") {
      await onAdjust("hline", { y: currentHlineY, color: "red", linestyle: "--", label: "Cutoff" });
    } else if (target === "vline") {
      await onAdjust("vline", { x: currentVlineX, color: "blue", linestyle: "--", label: "Marker" });
    } else if (target === "ylim-top" || target === "ylim-bottom") {
      await onAdjust("ylim", { ymin: currentYlim[0], ymax: currentYlim[1] });
    } else if (target === "xlim-left" || target === "xlim-right") {
      await onAdjust("xlim", { xmin: currentXlim[0], xmax: currentXlim[1] });
    }
  };

  const xlimLeftPixelX = xDataToPixel(currentXlim[0]);
  const xlimRightPixelX = xDataToPixel(currentXlim[1]);

  const hlinePixelY = Math.max(plotTop, Math.min(plotBottom, yDataToPixel(currentHlineY)));
  const vlinePixelX = Math.max(plotLeft, Math.min(plotRight, xDataToPixel(currentVlineX)));
  const ylimTopPixelY = yDataToPixel(currentYlim[1]);
  const ylimBottomPixelY = yDataToPixel(currentYlim[0]);

  return (
    <div
      ref={containerRef}
      className={`interactive-manipulator-overlay${draggingTarget ? " dragging" : ""}`}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
    >
      {/* 顶部工具选项卡 */}
      <div className="manipulator-toolbar">
        <div className="manipulator-title">
          <span className="manipulator-icon">🎯</span>
          <span>{language === "zh" ? "交互式图像修正模式" : "Interactive Plot Correction"}</span>
        </div>

        <div className="manipulator-tool-group">
          <button
            type="button"
            className={`manipulator-tool-btn${activeTool === "hline" ? " active" : ""}`}
            onClick={() => setActiveTool("hline")}
            title="拖动水平阈值参考线 (ax.axhline)"
          >
            <span>➖</span>
            <span>{language === "zh" ? "水平阈值线" : "Cutoff Line"}</span>
          </button>

          <button
            type="button"
            className={`manipulator-tool-btn${activeTool === "vline" ? " active" : ""}`}
            onClick={() => setActiveTool("vline")}
            title="拖动垂直标记线 (ax.axvline)"
          >
            <span>┆</span>
            <span>{language === "zh" ? "垂直标记线" : "Marker Line"}</span>
          </button>

          <button
            type="button"
            className={`manipulator-tool-btn${activeTool === "ylim" ? " active" : ""}`}
            onClick={() => setActiveTool("ylim")}
            title="拉动坐标轴上/下边界手柄扩展范围 (ax.set_ylim)"
          >
            <span>↕️</span>
            <span>{language === "zh" ? "Y 轴范围" : "Y limits"}</span>
          </button>

          <button
            type="button"
            className={`manipulator-tool-btn${activeTool === "xlim" ? " active" : ""}`}
            onClick={() => setActiveTool("xlim")}
            title="拉动坐标轴左/右边界手柄调整范围 (ax.set_xlim)"
          >
            <span>↔️</span>
            <span>{language === "zh" ? "X 轴范围" : "X limits"}</span>
          </button>
        </div>

        <button
          type="button"
          className="manipulator-close-btn"
          onClick={onClose}
          title={language === "zh" ? "退出交互修正模式" : "Exit"}
        >
          ✕
        </button>
      </div>

      {/* 拖动提示浮动徽章 */}
      {dragValueLabel && (
        <div
          className="manipulator-tooltip-badge"
          style={{
            left: draggingTarget === "vline" ? `${vlinePixelX + 12}px` : `${plotLeft + plotWidth / 2}px`,
            top: draggingTarget === "hline" ? `${hlinePixelY - 28}px` : `${plotTop + 16}px`,
          }}
        >
          {dragValueLabel}
        </div>
      )}

      {/* 绘图主轴区域指示虚线边框 */}
      <div
        className="manipulator-plot-box"
        style={{
          left: `${plotLeft}px`,
          top: `${plotTop}px`,
          width: `${plotWidth}px`,
          height: `${plotHeight}px`,
        }}
      />

      {/* 1. 水平阈值线 (Horizontal Cutoff Line) */}
      {(activeTool === "hline" || draggingTarget === "hline") && (
        <div
          className={`manipulator-hline${draggingTarget === "hline" ? " active" : ""}`}
          style={{
            left: `${plotLeft}px`,
            width: `${plotWidth}px`,
            top: `${hlinePixelY}px`,
          }}
          onPointerDown={(e) => {
            e.stopPropagation();
            setDraggingTarget("hline");
            setDragValueLabel(`Cutoff: y = ${currentHlineY}`);
          }}
        >
          <div className="manipulator-line-body" />
          <div className="manipulator-handle h-handle">
            <span className="handle-dot" />
            <span className="handle-tag">y = {currentHlineY}</span>
          </div>
        </div>
      )}

      {/* 2. 垂直标记线 (Vertical Marker Line) */}
      {(activeTool === "vline" || draggingTarget === "vline") && (
        <div
          className={`manipulator-vline${draggingTarget === "vline" ? " active" : ""}`}
          style={{
            left: `${vlinePixelX}px`,
            top: `${plotTop}px`,
            height: `${plotHeight}px`,
          }}
          onPointerDown={(e) => {
            e.stopPropagation();
            setDraggingTarget("vline");
            setDragValueLabel(`Marker: x = ${currentVlineX}`);
          }}
        >
          <div className="manipulator-line-body" />
          <div className="manipulator-handle v-handle">
            <span className="handle-dot" />
            <span className="handle-tag">x = {currentVlineX}</span>
          </div>
        </div>
      )}

      {/* 3. Y 轴范围拉伸边界 (Top / Bottom Bounds) */}
      {(activeTool === "ylim" || draggingTarget?.startsWith("ylim")) && (
        <>
          {/* 上界手柄 */}
          <div
            className={`manipulator-limit-rail top${draggingTarget === "ylim-top" ? " active" : ""}`}
            style={{
              left: `${plotLeft}px`,
              width: `${plotWidth}px`,
              top: `${ylimTopPixelY}px`,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              setDraggingTarget("ylim-top");
              setDragValueLabel(`Y-Max = ${currentYlim[1]}`);
            }}
          >
            <div className="limit-handle-pill">
              <span>▲ Y-Max: {currentYlim[1]}</span>
            </div>
          </div>

          {/* 下界手柄 */}
          <div
            className={`manipulator-limit-rail bottom${draggingTarget === "ylim-bottom" ? " active" : ""}`}
            style={{
              left: `${plotLeft}px`,
              width: `${plotWidth}px`,
              top: `${ylimBottomPixelY}px`,
            }}
            onPointerDown={(e) => {
              e.stopPropagation();
              setDraggingTarget("ylim-bottom");
              setDragValueLabel(`Y-Min = ${currentYlim[0]}`);
            }}
          >
            <div className="limit-handle-pill">
              <span>▼ Y-Min: {currentYlim[0]}</span>
            </div>
          </div>
        </>
      )}

      {/* 4. X 轴范围左右边界 */}
      {(activeTool === "xlim" || draggingTarget?.startsWith("xlim")) && (
        <>
          {([
            ["xlim-left", xlimLeftPixelX, `◀ X-Min: ${currentXlim[0]}`],
            ["xlim-right", xlimRightPixelX, `X-Max: ${currentXlim[1]} ▶`],
          ] as [DragTarget, number, string][]).map(([target, left, text]) => (
            <div
              key={target}
              className={`manipulator-limit-rail vertical${draggingTarget === target ? " active" : ""}`}
              style={{ left: `${left}px`, top: `${plotTop}px`, height: `${plotHeight}px` }}
              onPointerDown={(e) => {
                e.stopPropagation();
                setDraggingTarget(target);
                setDragValueLabel(text);
              }}
            >
              <div className="limit-handle-pill">
                <span>{text}</span>
              </div>
            </div>
          ))}
        </>
      )}

      {/* 底部引导提示 */}
      <div className="manipulator-footer-tip">
        <span>
          {language === "zh"
            ? busy
              ? "⏳ 正在同步更新 Python 代码并重新渲染…"
              : "💡 拖拽上述参考线或边界手柄，释放后自动同步修改底层 Python 绘图代码"
            : busy
            ? "⏳ Updating Python script & re-rendering…"
            : "💡 Drag lines or boundary handles; releasing will auto-update Python code"}
        </span>
      </div>
    </div>
  );
}
