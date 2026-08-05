import type { CodeParameter, ConnectionResult, DatasetInfo, LLMConfig, PlotResult, Preset, RevisionSummary } from "./types";

const BASE = import.meta.env.DEV ? "/api" : "http://127.0.0.1:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error((data as { detail?: string }).detail || `请求失败 (${resp.status})`);
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

export async function editPlot(datasetId: string, code: string, instruction: string, preset?: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code, instruction, preset }),
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

export async function updateLLMConfig(input: {
  api_key?: string;
  base_url: string;
  model: string;
  mock: boolean;
  auto_repair_attempts: number;
  sandbox_mode: "process" | "docker";
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
