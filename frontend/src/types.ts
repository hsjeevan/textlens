export type RunStatus = "pending" | "running" | "completed" | "failed";
export type StepSource = "cache" | "nlp";

export interface Keyword {
  word: string;
  count: number;
}

export interface Tone {
  label: string;
  scores: { neg: number; neu: number; pos: number; compound: number };
  indicators: { exclamation_count: number; question_count: number; uppercase_word_ratio: number };
}

export interface Themes {
  scores: Record<string, number>;
  dominant: string[];
}

export interface AnalysisResult {
  word_count: number;
  sentence_count: number;
  top_keywords: Keyword[];
  tone: Tone;
  themes: Themes;
}

export interface CacheInfo {
  result: StepSource;
  steps?: Record<string, StepSource>;
  forced?: boolean;
}

export interface Run {
  run_id: string;
  status: RunStatus;
  filename?: string | null;
  flow_run_id?: string | null;
  cache_hit?: boolean;
  cache?: CacheInfo | null;
  result?: AnalysisResult;
  error?: string | null;
}

export interface UploadResponse {
  run_id: string;
  status: RunStatus;
  force: boolean;
  status_url: string;
}
