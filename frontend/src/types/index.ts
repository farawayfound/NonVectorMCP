export interface User {
  user_id: string;
  github_username: string | null;
  display_name: string | null;
  avatar_url: string | null;
  role: "admin" | "recruiter";
}

export interface AuthStatus {
  authenticated: boolean;
  user: User | null;
  github_enabled: boolean;
}

export interface Document {
  filename: string;
  size_bytes: number;
  modified: string;
  suffix: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface SearchResult {
  id: string;
  text: string;
  tags: string[];
  MatchType: string;
  RelevanceScore: number;
  metadata: Record<string, unknown>;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_more: boolean;
  level: string;
  phases: Record<string, number>;
}

export interface InviteCode {
  code: string;
  created_by: string | null;
  created_at: string;
  expires_at: string | null;
  max_uses: number;
  use_count: number;
  label: string;
  active: number;
}

export interface IndexStatus {
  job: { status: string; error: string | null };
  last_run: { completed: string; chunks: number; files: number } | null;
}
