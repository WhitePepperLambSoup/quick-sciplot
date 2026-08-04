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
  parameters: CodeParameter[];
}

export interface CodeParameter {
  id: string;
  name: string;
  label: string;
  value: string;
  source: string;
  type: "string" | "number" | "boolean" | "literal";
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
}

export interface PlotRun {
  success: boolean;
  returncode: number;
  stdout: string;
  stderr: string;
  formats: string[];
  interactive?: PlotlyFigure;
  image?: string;
  size_bytes?: number;
}

export interface PlotlyFigure {
  data: unknown[];
  layout?: Record<string, unknown>;
  frames?: unknown[];
}

export interface PlotResult {
  code: string;
  preset: string;
  revision_id: string;
  export_formats: string[];
  repair_attempts: number;
  statements: StatementCard[];
  run: PlotRun;
}

export interface RevisionSummary {
  id: string;
  dataset_id: string;
  preset: string;
  operation: string;
  success: boolean;
  created_at: string;
}

export interface LLMConfig {
  base_url: string;
  model: string;
  mock: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  auto_repair_attempts: number;
  sandbox_timeout: number;
}

export interface ConnectionResult {
  ok: boolean;
  mode: string;
  latency_ms: number;
  preview: string;
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
