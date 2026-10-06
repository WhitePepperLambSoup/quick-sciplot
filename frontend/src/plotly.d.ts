declare module "plotly.js-dist-min" {
  /** Internal (but long-stable) axis object from ``gd._fullLayout``. */
  export interface PlotlyFullAxis {
    _offset: number;
    _length: number;
    type?: string;
    d2p: (value: unknown) => number;
    p2d: (pixel: number) => unknown;
  }

  export interface PlotlyElement extends HTMLElement {
    on: (event: string, handler: (payload: Record<string, unknown>) => void) => void;
    removeAllListeners?: (event: string) => void;
    layout?: { xaxis?: { range?: unknown[] }; yaxis?: { range?: unknown[] } };
    _fullLayout?: Record<string, PlotlyFullAxis | unknown>;
    calcdata?: Array<Array<Record<string, unknown>>>;
  }

  const Plotly: {
    newPlot: (element: HTMLElement, data: unknown[], layout?: Record<string, unknown>, config?: Record<string, unknown>) => Promise<PlotlyElement>;
    purge: (element: HTMLElement) => void;
  };

  export default Plotly;
}
