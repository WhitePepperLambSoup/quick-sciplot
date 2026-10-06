declare module "plotly.js-dist-min" {
  export interface PlotlyElement extends HTMLElement {
    on: (event: string, handler: (payload: Record<string, unknown>) => void) => void;
    removeAllListeners?: (event: string) => void;
    layout?: { xaxis?: { range?: unknown[] }; yaxis?: { range?: unknown[] } };
  }

  const Plotly: {
    newPlot: (element: HTMLElement, data: unknown[], layout?: Record<string, unknown>, config?: Record<string, unknown>) => Promise<PlotlyElement>;
    purge: (element: HTMLElement) => void;
  };

  export default Plotly;
}
