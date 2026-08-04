export interface ColumnSummary {
  name: string;
  dtype: string;
  nulls: number;
  n_unique: number;
  min?: number;
  max?: number;
  mean?: number;
  median?: number;
  std?: number;
  top_values?: { value: string; count: number }[];
}

export interface DataSummary {
  shape: { rows: number; cols: number };
  columns: ColumnSummary[];
  head: Record<string, unknown>[];
}

export interface DatasetInfo {
  id: string;
  summary: DataSummary;
}

export interface StatementCard {
  start: number;
  end: number;
  code: string;
  label: string;
  tags: string[];
}

export interface PlotRun {
  success: boolean;
  returncode: number;
  stdout: string;
  stderr: string;
  image?: string;
  size_bytes?: number;
}

export interface PlotResult {
  code: string;
  preset: string;
  statements: StatementCard[];
  run: PlotRun;
}

export interface Preset {
  id: string;
  name: string;
  description: string;
  source: string;
  source_url: string;
  category: string;
  local_available: boolean;
  has_fallback: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  error?: boolean;
}
