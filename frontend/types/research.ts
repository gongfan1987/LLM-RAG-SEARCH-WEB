export interface Provenance {
  agent: string;
  source: string | null;
  created_at: string;
}

export interface ResearchTaskSummary {
  id: number;
  topic: string;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ResearchTaskDetail extends ResearchTaskSummary {
  outline: Array<{ id: string; title: string; points: string[]; provenance: Provenance }>;
  assumptions: Array<Record<string, unknown>>;
  facts: Array<{ id: string; content: string; provenance: Provenance }>;
  data_points: Array<Record<string, unknown>>;
  charts: Array<Record<string, unknown>>;
  drafts: Array<Record<string, unknown>>;
  final: Record<string, unknown> | null;
  reviews: Array<Record<string, unknown>>;
}

export interface CreateResearchTaskPayload {
  topic: string;
  session_id?: number;
}
