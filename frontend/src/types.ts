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
  name?: string;
  summary: DataSummary;
}

export interface StatementCard {
  start: number;
  end: number;
  code: string;
  label: string;
  tags: string[];
  parameters: CodeParameter[];
  explanation_zh: string;
  explanation_en: string;
  data_bindings: DataBinding[];
}

export interface DataBinding {
  axis: string;
  column: string;
  meaning_zh: string;
  meaning_en: string;
}

export interface CodeParameter {
  id: string;
  name: string;
  label: string;
  value: string;
  source: string;
  type: "string" | "number" | "boolean" | "literal" | "column" | "column_name";
  options?: string[];
  meaning_zh?: string;
  meaning_en?: string;
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
  /** 1-based line in the user's code where the run failed, when known. */
  error_line?: number;
  repair_error?: string;
}

export interface PlotlyFigure {
  data: unknown[];
  layout?: Record<string, unknown>;
  frames?: unknown[];
}

export interface PlotMeta {
  xlim: [number, number];
  ylim: [number, number];
  bbox: [number, number, number, number]; // [left, bottom, width, height] normalized
}

export interface InspectedElements {
  hlines: number[];
  vlines: number[];
  ylim: [number, number] | null;
  xlim: [number, number] | null;
}

export interface PlotResult {
  code: string;
  preset: string;
  revision_id: string;
  export_formats: string[];
  repair_attempts: number;
  statements: StatementCard[];
  meta?: PlotMeta;
  inspected?: InspectedElements;
  run: PlotRun;
  stats_results?: unknown[];
  regression?: RegressionFit;
  width_inches?: number;
}

export interface RevisionSummary {
  id: string;
  dataset_id: string;
  preset: string;
  operation: string;
  success: boolean;
  created_at: string;
  label?: string;
  starred?: boolean;
}

export interface RevisionDetail extends RevisionSummary {
  code: string;
  stderr: string;
}

export interface RegressionFit {
  x_col: string;
  y_col: string;
  degree: number;
  n: number;
  coefficients: number[];
  r_squared: number;
  p_value?: number;
  equation: string;
}

export interface SystemStatus {
  sandbox_mode: "process" | "docker";
  sandbox_ready: boolean;
  process_allowed: boolean;
  desktop: boolean;
  can_enable_process: boolean;
  can_build_image: boolean;
  docker: { installed: boolean; daemon_running: boolean; image_present: boolean; image: string };
  image_build: { state: "idle" | "running" | "succeeded" | "failed"; error: string; log: string[] };
  llm_configured: boolean;
  llm_mock: boolean;
}

export interface DatasetPreview {
  columns: string[];
  dtypes: Record<string, string>;
  rows: Record<string, unknown>[];
  offset: number;
  total_rows: number;
}

export interface ColumnValues {
  column: string;
  values: { value: string; count: number }[];
  total_unique: number;
  truncated: boolean;
}

export type TransformOperation = { op: string } & Record<string, unknown>;

export interface TemplateParam {
  name: string;
  label_zh: string;
  label_en: string;
  kind: "column" | "numeric" | "numeric_multi" | "number" | "choice";
  required: boolean;
  default: unknown;
  options: string[];
  minimum: number | null;
  maximum: number | null;
}

export interface TemplateInfo {
  id: string;
  name_zh: string;
  name_en: string;
  description_zh: string;
  description_en: string;
  params: TemplateParam[];
}

export interface BatchItem {
  dataset_id: string;
  name?: string;
  revision_id?: string;
  success: boolean;
  stderr?: string;
  error?: string;
  export_formats?: string[];
}

export type StreamStage = "llm" | "render" | "repair";

export type StreamEvent =
  | { type: "stage"; stage: StreamStage }
  | { type: "token"; text: string }
  | { type: "result"; data: PlotResult }
  | { type: "error"; status: number; detail: string }
  | { type: "cancelled" }
  | { type: "ping" };

export interface CritiqueReport {
  score: number;
  suggestions: string[];
  has_overlap: boolean;
  legend_ok: boolean;
  dpi_ok: boolean;
  repair_prompt: string;
  ai?: { available: boolean; score?: number; issues?: string[]; suggestions?: string[]; error?: string };
}

export interface LLMConfig {
  base_url: string;
  model: string;
  mock: boolean;
  has_api_key: boolean;
  api_key_masked: string;
  auto_repair_attempts: number;
  sandbox_timeout: number;
  sandbox_mode: "process" | "docker";
  send_data_values: boolean;
  allow_loopback_llm?: boolean;
  desktop?: boolean;
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

export interface StatAnnotationRequest {
  dataset_id: string;
  code: string;
  group_col: string;
  val_col: string;
  pairs: [string, string][];
  test_type?: "t-test" | "mann-whitney" | "anova";
}

export interface CritiqueResult {
  score: number;
  suggestions: string[];
  has_overlap: boolean;
  legend_ok: boolean;
}
