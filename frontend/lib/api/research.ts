import { apiFetch } from "@/lib/api/client";
import type {
  CreateResearchTaskPayload,
  ResearchTaskDetail,
  ResearchTaskSummary,
} from "@/types/research";

export function fetchResearchTasks(): Promise<ResearchTaskSummary[]> {
  return apiFetch<ResearchTaskSummary[]>("/api/research/tasks");
}

export function fetchResearchTask(id: number): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>(`/api/research/tasks/${id}`);
}

export function createResearchTask(
  payload: CreateResearchTaskPayload
): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>("/api/research/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function appendResearchField(
  id: number,
  payload: { field: string; items: Array<Record<string, unknown>> }
): Promise<ResearchTaskDetail> {
  return apiFetch<ResearchTaskDetail>(`/api/research/tasks/${id}/append`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
