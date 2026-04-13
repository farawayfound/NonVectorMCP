const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || body.error || res.statusText);
  }
  return res.json();
}

// Auth
export const getAuthStatus = () => request<any>("/auth/status");
export const loginWithInvite = (code: string) =>
  request<any>("/auth/invite", { method: "POST", body: JSON.stringify({ code }) });
export const logout = () => request<any>("/auth/logout", { method: "POST" });
export const requestAccess = (email: string) =>
  request<any>("/auth/request-access", { method: "POST", body: JSON.stringify({ email }) });

// Chat quota
export const getChatQuota = () => request<any>("/chat/quota");

// Chat
export const getChatHealth = () => request<any>("/chat/health");

export interface ChatStreamEvent {
  text?: string;
  thinking?: string;
  phase?: string;
}

export async function* streamChat(
  endpoint: "/chat/ask" | "/chat/documents",
  body: Record<string, unknown>,
): AsyncGenerator<ChatStreamEvent> {
  const res = await fetch(`${BASE}${endpoint}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const raw = await res.text();
    let detail = raw.slice(0, 800).trim() || res.statusText;
    try {
      const j = JSON.parse(raw) as { detail?: string; error?: string };
      detail = (j.detail || j.error || detail) as string;
    } catch {
      // use raw slice
    }
    throw new Error(`Chat request failed (${res.status}): ${detail}`);
  }
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          const parsed = JSON.parse(data);
          yield parsed as ChatStreamEvent;
        } catch {
          // skip
        }
      }
    }
  }
}

// Search
export const searchDocuments = (body: Record<string, unknown>) =>
  request<any>("/chat/search", { method: "POST", body: JSON.stringify(body) });

// Documents
export const listDocuments = () => request<any>("/documents/");
export const deleteDocument = (filename: string) =>
  request<any>(`/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
export const getDocumentStats = () => request<any>("/documents/stats");

export async function uploadDocument(file: File): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/documents/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(body.detail || "Upload failed");
  }
  return res.json();
}

// Index
export interface BuildIndexOptions {
  generate_insights?: boolean;
  notify_email?: string;
}
export const buildIndex = (opts: BuildIndexOptions = {}) =>
  request<any>("/index/build", { method: "POST", body: JSON.stringify(opts) });
export const getIndexStatus = () => request<any>("/index/status");
export const getIndexStats = () => request<any>("/index/stats");
export const getIndexEmailStatus = () =>
  request<{ has_email: boolean; email: string }>("/index/email-status");

// Chunking config
export const getChunkingConfig = () => request<any>("/documents/config");
export const updateChunkingConfig = (config: Record<string, unknown>) =>
  request<any>("/documents/config", { method: "PUT", body: JSON.stringify(config) });

// Token metrics
export const getTokenMetrics = () => request<any>("/documents/metrics");

// User agent config (system prompt/rules for Your Documents)
export const getAgentConfig = () => request<any>("/documents/agent-config");
export const updateAgentConfig = (body: Record<string, unknown>) =>
  request<any>("/documents/agent-config", { method: "PUT", body: JSON.stringify(body) });

// Delete all user documents and indexes
export const deleteAllDocuments = () =>
  request<any>("/documents/all", { method: "DELETE" });

// Workspace — Insights
export const getDocumentInsights = (docId: string, refresh = false) =>
  request<any>(`/documents/insights/${encodeURIComponent(docId)}${refresh ? "?refresh=true" : ""}`);

// Workspace — Chunk Explorer
export interface ChunkQuery {
  doc_id?: string;
  category?: string;
  tag?: string;
  entity?: string;
  q?: string;
  limit?: number;
  offset?: number;
}
export const listChunks = (params: ChunkQuery = {}) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return request<any>(`/documents/chunks${suffix}`);
};

// Preserve data preference
export const getPreserveFlag = () => request<any>("/documents/preserve");
export const setPreserveFlag = (preserve: boolean) =>
  request<any>("/documents/preserve", { method: "PUT", body: JSON.stringify({ preserve }) });

// Admin
export const getAdminStats = () => request<any>("/admin/stats");
export const getAdminUsers = () => request<any>("/admin/users");
export const getInviteCodes = () => request<any>("/admin/invite-codes");
export const createInviteCode = (body: Record<string, unknown>) =>
  request<any>("/admin/invite-codes", { method: "POST", body: JSON.stringify(body) });
export const deactivateInviteCode = (code: string) =>
  request<any>(`/admin/invite-codes/${code}`, { method: "DELETE" });
export const getAdminActivity = (params?: Record<string, string>) => {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  return request<any>(`/admin/activity${qs}`);
};
export const getAdminOllama = () => request<any>("/admin/ollama");

// Admin — Ollama management
export const setOllamaModel = (name: string) =>
  request<any>("/admin/ollama/model", { method: "PUT", body: JSON.stringify({ name }) });
export const deleteOllamaModel = (name: string) =>
  request<any>("/admin/ollama/delete", { method: "POST", body: JSON.stringify({ name }) });
export const loadOllamaModel = (name: string) =>
  request<any>("/admin/ollama/load", { method: "POST", body: JSON.stringify({ name }) });
export const unloadOllamaModel = (name: string) =>
  request<any>("/admin/ollama/unload", { method: "POST", body: JSON.stringify({ name }) });

export async function* streamOllamaPull(name: string): AsyncGenerator<any> {
  const res = await fetch(`${BASE}/admin/ollama/pull`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Pull request failed");
  const reader = res.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        try {
          yield JSON.parse(data);
        } catch {
          // skip
        }
      }
    }
  }
}

// Chat — Suggestions
export const getChatSuggestions = () => request<{ suggestions: string[] }>("/chat/suggestions");

// Admin — Demo KB
export const getDemoDocuments = () => request<any>("/admin/demo/documents");
export const deleteDemoDocument = (filename: string) =>
  request<any>(`/admin/demo/documents/${encodeURIComponent(filename)}`, { method: "DELETE" });
export const buildDemoIndex = () =>
  request<any>("/admin/demo/build", { method: "POST" });
export const getDemoStatus = () => request<any>("/admin/demo/status");

// Admin — Performance log
export const getPerfLog = (page = 1, pageSize = 20) =>
  request<any>(`/admin/perf?page=${page}&page_size=${pageSize}`);
export const getPerfEntry = (id: number) => request<any>(`/admin/perf/${id}`);

// Admin — Suggestion model
export const setSuggestionModel = (name: string) =>
  request<any>("/admin/ollama/suggestion-model", { method: "PUT", body: JSON.stringify({ name }) });

// Admin — Demo KB suggestions
export const getDemoSuggestions = () => request<any>("/admin/demo/suggestions");
export const updateDemoSuggestions = (suggestions: string[]) =>
  request<any>("/admin/demo/suggestions", { method: "PUT", body: JSON.stringify({ suggestions }) });
export const addDemoSuggestion = (question: string) =>
  request<any>("/admin/demo/suggestions", { method: "POST", body: JSON.stringify({ question }) });
export const deleteDemoSuggestion = (index: number) =>
  request<any>(`/admin/demo/suggestions/${index}`, { method: "DELETE" });

// Admin — Default Q&A / STAR stories
export const getDemoQA = () => request<any>("/admin/demo/qa");
export const createDemoQA = (item: Record<string, unknown>) =>
  request<any>("/admin/demo/qa", { method: "POST", body: JSON.stringify(item) });
export const updateDemoQA = (id: string, item: Record<string, unknown>) =>
  request<any>(`/admin/demo/qa/${id}`, { method: "PUT", body: JSON.stringify(item) });
export const deleteDemoQA = (id: string) =>
  request<any>(`/admin/demo/qa/${id}`, { method: "DELETE" });

// Admin — Runtime configuration
export const getAdminConfig = () => request<any>("/admin/config");
export const updateAdminConfig = (body: Record<string, unknown>) =>
  request<any>("/admin/config", { method: "PUT", body: JSON.stringify(body) });

// Library — distributed research
export const submitResearch = (prompt: string, options?: Record<string, unknown>) =>
  request<any>("/library/research", {
    method: "POST",
    body: JSON.stringify({ prompt, ...options }),
  });
export const getLibraryTasks = () => request<any>("/library/tasks");
export const getLibraryTask = (id: string) => request<any>(`/library/tasks/${id}`);
export const approveLibraryTask = (id: string) =>
  request<any>(`/library/tasks/${id}/approve`, { method: "POST" });
export const rejectLibraryTask = (id: string) =>
  request<any>(`/library/tasks/${id}/reject`, { method: "POST" });
export const deleteLibraryTask = (id: string) =>
  request<any>(`/library/tasks/${id}`, { method: "DELETE" });

export function subscribeTaskStatus(taskId: string, onEvent: (data: any) => void, onDone: () => void) {
  const es = new EventSource(`${BASE}/library/tasks/${taskId}/stream`);
  es.onmessage = (e) => {
    if (e.data === "[DONE]") {
      es.close();
      onDone();
      return;
    }
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      // skip
    }
  };
  es.onerror = () => {
    es.close();
    onDone();
  };
  return () => es.close();
}

export async function uploadDemoDocument(file: File): Promise<any> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/admin/demo/upload`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(body.detail || "Upload failed");
  }
  return res.json();
}
