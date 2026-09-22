import type {
  GeneratedFlowDetail,
  CaseRunDetail,
  GenerationSummary,
  HealthResponse,
  Problem,
  RunSummary,
  ValidationReport,
  WorkbookSummary,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let problem: Problem | null = null;
    try {
      problem = (await response.json()) as Problem;
    } catch {
      // Use the HTTP fallback below when the response is not JSON.
    }
    throw new Error(problem?.message ?? `API ${response.status}: ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export const getHealth = (signal?: AbortSignal) =>
  request<HealthResponse>("/api/v1/health", { signal });

export function uploadWorkbook(file: File): Promise<WorkbookSummary> {
  const body = new FormData();
  body.append("file", file);
  return request<WorkbookSummary>("/api/v1/workbooks", { method: "POST", body });
}

export const getWorkbookValidation = (workbookId: string) =>
  request<ValidationReport>(`/api/v1/workbooks/${workbookId}/validation`);

export const createGeneration = (
  workbookId: string,
  mode: "review" | "unattended",
) =>
  request<GenerationSummary>("/api/v1/generations", {
    method: "POST",
    body: JSON.stringify({ workbook_id: workbookId, mode }),
  });

export const getGeneratedFlow = (generationId: string, flowId: string) =>
  request<GeneratedFlowDetail>(
    `/api/v1/generations/${generationId}/flows/${encodeURIComponent(flowId)}`,
  );

export const approveFlows = (generationId: string, flowIds: string[]) =>
  request<GenerationSummary>(`/api/v1/generations/${generationId}/approval`, {
    method: "POST",
    body: JSON.stringify({ flow_ids: flowIds }),
  });

export const createRun = (generationId: string) =>
  request<RunSummary>("/api/v1/runs", {
    method: "POST",
    body: JSON.stringify({ generation_id: generationId }),
  });

export const getRun = (runId: string) =>
  request<RunSummary>(`/api/v1/runs/${runId}`);

export const cancelRun = (runId: string) =>
  request<RunSummary>(`/api/v1/runs/${runId}/cancel`, { method: "POST" });

export const getCaseRun = (runId: string, caseId: string) =>
  request<CaseRunDetail>(
    `/api/v1/runs/${runId}/cases/${encodeURIComponent(caseId)}`,
  );

export const artifactUrl = (runId: string, artifactId: string) =>
  `${API_BASE}/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`;

export const resultWorkbookUrl = (runId: string) =>
  `${API_BASE}/api/v1/runs/${encodeURIComponent(runId)}/result-workbook`;
