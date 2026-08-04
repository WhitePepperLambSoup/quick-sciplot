import type { DatasetInfo, PlotResult } from "./types";

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

export async function generatePlot(datasetId: string, instruction: string, preset?: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, instruction, preset }),
  });
}

export async function editPlot(datasetId: string, code: string, instruction: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code, instruction }),
  });
}

export async function runCode(datasetId: string, code: string): Promise<PlotResult> {
  return request<PlotResult>("/plots/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, code }),
  });
}
