import { useEffect, useRef } from "react";
import type { PlotlyElement } from "plotly.js-dist-min";
import type { PlotlyFigure } from "../types";

export interface AxisRanges {
  x?: [number, number];
  y?: [number, number];
}

interface InteractivePlotProps {
  figure: PlotlyFigure;
  /** Called with the visible axis ranges whenever the user zooms or pans. */
  onRangesChange?: (ranges: AxisRanges) => void;
  /** Called with the graph div after every (re)draw, e.g. to place overlays. */
  onLayout?: (graph: PlotlyElement | null) => void;
}

function numericRange(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length !== 2) return undefined;
  const [low, high] = value.map(Number);
  return Number.isFinite(low) && Number.isFinite(high) ? [low, high] : undefined;
}

export function InteractivePlot({ figure, onRangesChange, onLayout }: InteractivePlotProps) {
  const plotRef = useRef<HTMLDivElement>(null);
  const callbackRef = useRef(onRangesChange);
  callbackRef.current = onRangesChange;
  const layoutRef = useRef(onLayout);
  layoutRef.current = onLayout;

  useEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    let disposed = false;
    void import("plotly.js-dist-min").then(async ({ default: Plotly }) => {
      if (disposed) return;
      const graph = await Plotly.newPlot(element, figure.data, figure.layout || {}, {
        responsive: true,
        displaylogo: false,
      });
      const report = () => {
        callbackRef.current?.({
          x: numericRange(graph.layout?.xaxis?.range),
          y: numericRange(graph.layout?.yaxis?.range),
        });
        layoutRef.current?.(graph);
      };
      report();
      graph.on("plotly_relayout", report);
      graph.on("plotly_afterplot", () => layoutRef.current?.(graph));
    });
    return () => {
      disposed = true;
      layoutRef.current?.(null);
      void import("plotly.js-dist-min").then(({ default: Plotly }) => Plotly.purge(element));
    };
  }, [figure]);

  return <div ref={plotRef} className="interactive-plot" aria-label="交互式 Plotly 图表" />;
}
