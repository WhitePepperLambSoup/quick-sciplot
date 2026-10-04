import { useEffect, useRef } from "react";
import type { PlotlyFigure } from "../types";

interface InteractivePlotProps {
  figure: PlotlyFigure;
}

export function InteractivePlot({ figure }: InteractivePlotProps) {
  const plotRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = plotRef.current;
    if (!element) return;
    let disposed = false;
    void import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (disposed) return;
      void Plotly.newPlot(element, figure.data, figure.layout || {}, {
        responsive: true,
        displaylogo: false,
      });
    });
    return () => {
      disposed = true;
      void import("plotly.js-dist-min").then(({ default: Plotly }) => Plotly.purge(element));
    };
  }, [figure]);

  return <div ref={plotRef} className="interactive-plot" aria-label="交互式 Plotly 图表" />;
}
