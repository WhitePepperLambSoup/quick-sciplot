import type { CodeParameter, ConnectionResult, DatasetInfo, LLMConfig, PlotResult, Preset, RevisionSummary } from "./types";

export const API_BASE = import.meta.env.DEV ? "/api" : "http://127.0.0.1:8000/api";

export function getExportUrl(revisionId: string, format: string): string {
  return `${API_BASE}/plots/revisions/${revisionId}/export/${format}`;
}

/**
 * FastAPI returns `detail` as a string for HTTPException but as an array of
 * `{ loc, msg }` objects for request-validation errors (422); passing the array
 * to `new Error` would display "[object Object]".
 */
export function errorDetail(data: unknown, fallback: string): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          const { loc, msg } = item as { loc?: unknown[]; msg?: unknown };
          const field = Array.isArray(loc) ? loc.filter((part) => part !== "body").join(".") : "";
          const message = typeof msg === "string" ? msg : "";
          return field && message ? `${field}: ${message}` : message || field;
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }
  return fallback;
}

type TauriInvoke = (command: string) => Promise<unknown>;

function tauriInvoke(): TauriInvoke | undefined {
  return (window as unknown as { __TAURI_INTERNALS__?: { invoke?: TauriInvoke } }).__TAURI_INTERNALS__?.invoke;
}

let desktopToken: Promise<string | null> | null = null;

/**
 * The packaged desktop window is served from http://tauri.localhost, which is
 * cross-site to the backend at http://127.0.0.1:8000.  Browsers drop the
 * backend's SameSite=Strict session cookie in that setup, so the Rust shell
 * hands over the session token and it is sent as the X-Session-Token header.
 * Plain browser sessions (no Tauri) keep using the cookie.
 */
function desktopSessionToken(refresh = false): Promise<string | null> {
  const invoke = tauriInvoke();
  if (!invoke) return Promise.resolve(null);
  if (refresh || desktopToken === null) {
    const pending = invoke("session_token")
      .then((token) => (typeof token === "string" && token ? token : null))
      .catch(() => null);
    desktopToken = pending;
    // Do not cache a failure: the token file may not exist yet while the backend starts.
    void pending.then((token) => {
      if (token === null && desktopToken === pending) desktopToken = null;
    });
  }
  return desktopToken;
}

async function withAuth(init: RequestInit | undefined, refreshToken = false): Promise<RequestInit> {
  const headers = new Headers(init?.headers);
  const token = await desktopSessionToken(refreshToken);
  if (token) headers.set("X-Session-Token", token);
  return { ...init, headers, credentials: "include" };
}

async function authorizedFetch(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, await withAuth(init));
  if (response.status === 401 && tauriInvoke()) {
    // The token may have been rotated since it was cached; read it once more.
    return fetch(url, await withAuth(init, true));
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await authorizedFetch(API_BASE + path, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(errorDetail(data, `请求失败 (${resp.status})`));
  }
  return data as T;
}

export async function uploadDataset(file: File): Promise<DatasetInfo> {
  const datasets = await uploadDatasets([file]);
  return datasets[0];
}

export async function uploadDatasets(files: File[]): Promise<DatasetInfo[]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  const data = await request<{ datasets?: DatasetInfo[]; id?: string; summary?: DatasetInfo["summary"] }>("/datasets", {
    method: "POST",
    body: form,
  });
  if (data.datasets?.length) return data.datasets;
  if (data.id && data.summary) return [{ id: data.id, name: files[0]?.name, summary: data.summary }];
  throw new Error("服务器没有返回导入的数据集");
}

export async function listDatasets(): Promise<DatasetInfo[]> {
  const data = await request<{ datasets: DatasetInfo[] }>("/datasets");
  return data.datasets || [];
}

export async function deleteDataset(datasetId: string): Promise<{ ok: boolean; id: string }> {
  return request<{ ok: boolean; id: string }>(`/datasets/${datasetId}`, {
    method: "DELETE",
  });
}

export async function combineDatasets(datasetIds: string[], name?: string): Promise<DatasetInfo> {
  return request<DatasetInfo>("/datasets/combine", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_ids: datasetIds, name }),
  });
}

export async function listPresets(): Promise<Preset[]> {
  const data = await request<{ presets: Preset[] }>("/presets");
  return data.presets;
}

export async function generatePlot(datasetId: string, instruction: string, preset?: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, instruction, preset }),
  });
}

export async function editPlot(
  datasetId: string,
  code: string,
  instruction: string,
  preset?: string,
  history?: { role: string; content: string }[],
): Promise<PlotResult> {
  return request<PlotResult>("/plots/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code, instruction, preset, history }),
  });
}

export async function runCode(datasetId: string, code: string, preset?: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code, preset }),
  });
}

export async function applyParameter(
  datasetId: string,
  code: string,
  parameter: CodeParameter,
  value: string,
  preset?: string,
): Promise<PlotResult> {
  return request<PlotResult>("/plots/parameter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code, parameter, value, preset }),
  });
}

export async function listHistory(datasetId: string): Promise<RevisionSummary[]> {
  const data = await request<{ revisions: RevisionSummary[] }>(`/plots/history/${datasetId}`);
  return data.revisions;
}

export async function restoreRevision(revisionId: string): Promise<PlotResult> {
  return request<PlotResult>(`/plots/history/${revisionId}/restore`, { method: "POST" });
}

export async function getConfig(): Promise<LLMConfig> {
  return request<LLMConfig>("/config");
}

export async function downloadExport(revisionId: string, format: string): Promise<Blob> {
  const response = await authorizedFetch(getExportUrl(revisionId, format));
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(errorDetail(data, `下载失败 (${response.status})`));
  }
  return response.blob();
}

export async function updateLLMConfig(input: {
  api_key?: string;
  base_url: string;
  model: string;
  mock: boolean;
  auto_repair_attempts: number;
  sandbox_mode: "process" | "docker";
  send_data_values: boolean;
}): Promise<LLMConfig> {
  return request<LLMConfig>("/config/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function testLLMConnection(): Promise<ConnectionResult> {
  return request<ConnectionResult>("/config/test", { method: "POST" });
}

export async function annotateStats(input: {
  dataset_id: string;
  code: string;
  group_col: string;
  val_col: string;
  pairs: string[][];
  test_type?: string;
  preset?: string;
}): Promise<PlotResult & { stats_results?: unknown[] }> {
  return request("/plots/stats", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function composePlots(input: {
  dataset_id: string;
  layout: string;
  panels: { title: string; code: string }[];
  preset?: string;
}): Promise<PlotResult> {
  return request("/plots/compose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function mimicPlot(input: {
  dataset_id: string;
  reference_description: string;
  reference_image_b64?: string;
  preset?: string;
}): Promise<PlotResult> {
  return request("/plots/mimic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function critiquePlot(revisionId: string): Promise<{
  score: number;
  suggestions: string[];
  has_overlap: boolean;
  legend_ok: boolean;
  dpi_ok: boolean;
  repair_prompt: string;
}> {
  return request("/plots/critique", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision_id: revisionId }),
  });
}

export async function checkCompliance(revisionId: string, journal: string = "nature"): Promise<{
  journal: string;
  passed: boolean;
  checks: { item: string; passed: boolean; detail: string }[];
  formats_found: string[];
}> {
  return request(`/plots/revisions/${revisionId}/compliance/${journal}`);
}

export async function getRevisionDetail(revisionId: string): Promise<{
  id: string;
  dataset_id: string;
  code: string;
  preset: string;
  operation: string;
  created_at: string;
}> {
  return request(`/plots/history/${revisionId}/detail`);
}

export async function interactiveAdjustPlot(input: {
  dataset_id: string;
  code: string;
  action: string;
  params: Record<string, unknown>;
  preset?: string;
}): Promise<PlotResult> {
  return request("/plots/interactive-adjust", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}
