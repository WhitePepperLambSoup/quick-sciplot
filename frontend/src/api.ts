import type { CodeParameter, DatasetInfo, PlotResult, Preset, RevisionSummary } from "./types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + path, init);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error((data as { detail?: string }).detail || `请求失败 (${resp.status})`);
  }
  return data as T;
}

export async function uploadDataset(file: File): Promise<DatasetInfo> {
  const form = new FormData();
  form.append("file", file);
  return request<DatasetInfo>("/datasets", { method: "POST", body: form });
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
