import React, { useState, useEffect, useCallback, useRef, type ReactNode } from "react";
import {
  getAdminStats,
  getAdminUsers,
  getInviteCodes,
  createInviteCode,
  deactivateInviteCode,
  getAdminActivity,
  getAdminOllama,
  deleteOllamaModel,
  loadOllamaModel,
  unloadOllamaModel,
  streamOllamaPull,
  setSuggestionModel,
  getDemoDocuments,
  deleteDemoDocument,
  uploadDemoDocument,
  buildDemoIndex,
  getDemoStatus,
  getDemoSuggestions,
  addDemoSuggestion,
  deleteDemoSuggestion,
  updateDemoSuggestions,
  getDemoQA,
  createDemoQA,
  updateDemoQA,
  deleteDemoQA,
  getPerfLog,
  getPerfEntry,
  getAdminConfig,
  updateAdminConfig,
} from "../api/client";
import type { InviteCode } from "../types";

type Tab = "overview" | "codes" | "users" | "activity" | "ollama" | "demokb" | "perf" | "configuration";

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  codes: "Codes",
  users: "Users",
  activity: "Activity",
  ollama: "Ollama",
  demokb: "Demo KB",
  perf: "Performance",
  configuration: "Configuration",
};

export function AdminPanel() {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <div className="admin-page">
      <h2>Admin Dashboard</h2>
      <div className="admin-tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            className={`tab ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>
      <div className="admin-content">
        {tab === "overview" && <OverviewTab />}
        {tab === "codes" && <CodesTab />}
        {tab === "users" && <UsersTab />}
        {tab === "activity" && <ActivityTab />}
        {tab === "ollama" && <OllamaTab />}
        {tab === "demokb" && <DemoKBTab />}
        {tab === "perf" && <PerformanceTab />}
        {tab === "configuration" && <ConfigurationTab />}
      </div>
    </div>
  );
}

function OverviewTab() {
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    getAdminStats().then(setStats).catch(() => {});
  }, []);

  if (!stats) return <p>Loading...</p>;
  return (
    <div className="stats-grid">
      <div className="stat-card"><div className="stat-value">{stats.users}</div><div className="stat-label">Users</div></div>
      <div className="stat-card"><div className="stat-value">{stats.active_invite_codes}</div><div className="stat-label">Active Codes</div></div>
      <div className="stat-card"><div className="stat-value">{stats.active_sessions}</div><div className="stat-label">Sessions</div></div>
      <div className="stat-card"><div className="stat-value">{stats.activity_last_24h}</div><div className="stat-label">Activity (24h)</div></div>
    </div>
  );
}

const EXPIRY_OPTIONS = [
  { label: "No expiration", value: "" },
  { label: "1 hour", value: "1h" },
  { label: "6 hours", value: "6h" },
  { label: "12 hours", value: "12h" },
  { label: "24 hours", value: "24h" },
  { label: "48 hours", value: "48h" },
  { label: "7 days", value: "7d" },
  { label: "30 days", value: "30d" },
] as const;

function expiryToISO(value: string): string | null {
  if (!value) return null;
  const now = new Date();
  const match = value.match(/^(\d+)(h|d)$/);
  if (!match) return null;
  const amount = parseInt(match[1], 10);
  const unit = match[2];
  if (unit === "h") now.setTime(now.getTime() + amount * 3600_000);
  else now.setTime(now.getTime() + amount * 86400_000);
  return now.toISOString();
}

function formatExpiry(expiresAt: string | null): string {
  if (!expiresAt) return "Never";
  const d = new Date(expiresAt);
  const now = new Date();
  if (d <= now) return "Expired";
  const diffMs = d.getTime() - now.getTime();
  const diffH = Math.floor(diffMs / 3600_000);
  if (diffH < 1) return `${Math.ceil(diffMs / 60_000)}m left`;
  if (diffH < 48) return `${diffH}h left`;
  return `${Math.floor(diffH / 24)}d left`;
}

function CodesTab() {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [label, setLabel] = useState("");
  const [maxUses, setMaxUses] = useState(0);
  const [expiry, setExpiry] = useState("48h");

  const load = useCallback(() => {
    getInviteCodes().then((d) => setCodes(d.codes)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    await createInviteCode({
      label,
      max_uses: maxUses,
      expires_at: expiryToISO(expiry),
    });
    setLabel("");
    setMaxUses(0);
    setExpiry("48h");
    load();
  };

  const handleDeactivate = async (code: string) => {
    await deactivateInviteCode(code);
    load();
  };

  const isExpired = (c: InviteCode) =>
    c.expires_at ? new Date(c.expires_at) <= new Date() : false;

  const statusLabel = (c: InviteCode) => {
    if (!c.active) return "Inactive";
    if (isExpired(c)) return "Expired";
    return "Active";
  };

  const statusColor = (c: InviteCode) => {
    if (!c.active) return "var(--text-muted)";
    if (isExpired(c)) return "var(--danger, #ef4444)";
    return "var(--success, #22c55e)";
  };

  return (
    <div>
      <div className="create-code-form">
        <input
          placeholder="Label (optional)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <label style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Max redemptions (0 = unlimited)
          </label>
          <input
            type="number"
            placeholder="0"
            value={maxUses}
            onChange={(e) => setMaxUses(Number(e.target.value))}
            min={0}
            title="Maximum number of times this invite code can be redeemed by different users. Set to 0 for unlimited."
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
          <label style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            Expires after
          </label>
          <select
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            style={{
              padding: "6px 10px",
              background: "var(--bg-card)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
            }}
          >
            {EXPIRY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <button className="btn btn-primary" onClick={handleCreate}>Create Code</button>
      </div>
      <table className="admin-table">
        <thead>
          <tr><th>Code</th><th>Label</th><th>Redemptions</th><th>Created</th><th>Expires</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {codes.map((c) => (
            <tr key={c.code} style={{ opacity: (!c.active || isExpired(c)) ? 0.55 : 1 }}>
              <td className="monospace">{c.code}</td>
              <td>{c.label || "-"}</td>
              <td>{c.use_count}{c.max_uses > 0 ? `/${c.max_uses}` : ""}</td>
              <td>{new Date(c.created_at).toLocaleDateString()}</td>
              <td title={c.expires_at ? new Date(c.expires_at).toLocaleString() : "No expiration"}>
                {formatExpiry(c.expires_at)}
              </td>
              <td style={{ color: statusColor(c) }}>{statusLabel(c)}</td>
              <td>
                {c.active && !isExpired(c) ? (
                  <button className="btn btn-sm btn-danger" onClick={() => handleDeactivate(c.code)}>
                    Deactivate
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<any[]>([]);
  useEffect(() => {
    getAdminUsers().then((d) => setUsers(d.users)).catch(() => {});
  }, []);

  return (
    <table className="admin-table">
      <thead>
        <tr><th>ID</th><th>Name</th><th>GitHub</th><th>Role</th><th>Created</th><th>Last Seen</th></tr>
      </thead>
      <tbody>
        {users.map((u) => (
          <tr key={u.id}>
            <td className="monospace">{u.id.slice(0, 8)}...</td>
            <td>{u.display_name || "-"}</td>
            <td>{u.github_username || "-"}</td>
            <td>{u.role}</td>
            <td>{new Date(u.created_at).toLocaleDateString()}</td>
            <td>{u.last_seen ? new Date(u.last_seen).toLocaleString() : "Never"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ActivityTab() {
  const [activity, setActivity] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [eventFilter, setEventFilter] = useState("");
  const [eventTypes, setEventTypes] = useState<string[]>([]);

  const load = useCallback(() => {
    const params: Record<string, string> = { limit: "200" };
    if (eventFilter) params.event = eventFilter;
    getAdminActivity(params).then((d) => {
      setActivity(d.activity);
      setTotal(d.total);
      // Collect unique event types for filter dropdown
      const types = new Set<string>(d.activity.map((a: any) => a.event));
      setEventTypes((prev) => {
        const merged = new Set([...prev, ...types]);
        return Array.from(merged).sort();
      });
    }).catch(() => {});
  }, [eventFilter]);

  useEffect(() => { load(); }, [load]);

  const formatDetails = (details: string | null) => {
    if (!details) return "-";
    try {
      const parsed = JSON.parse(details);
      return Object.entries(parsed)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
    } catch {
      return details;
    }
  };

  return (
    <div>
      <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginBottom: "1rem" }}>
        <select
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          style={{ padding: "6px 12px", background: "var(--bg-card)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px" }}
        >
          <option value="">All Events ({total})</option>
          {eventTypes.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <button className="btn btn-sm" onClick={load}>Refresh</button>
      </div>
      <table className="admin-table">
        <thead>
          <tr><th>Time</th><th>Event</th><th>User</th><th>Details</th></tr>
        </thead>
        <tbody>
          {activity.length === 0 ? (
            <tr><td colSpan={4} style={{ textAlign: "center", color: "var(--text-muted)" }}>No events recorded yet</td></tr>
          ) : (
            activity.map((a) => (
              <tr key={a.id}>
                <td style={{ whiteSpace: "nowrap" }}>{new Date(a.timestamp).toLocaleString()}</td>
                <td><span className="monospace" style={{ fontSize: "0.8rem" }}>{a.event}</span></td>
                <td className="monospace">{a.user_id ? a.user_id.slice(0, 8) + "..." : "-"}</td>
                <td className="truncate" title={a.details || ""}>{formatDetails(a.details)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function OllamaTab() {
  const [data, setData] = useState<any>(null);
  const [pullName, setPullName] = useState("");
  const [pullStatus, setPullStatus] = useState("");
  const [pulling, setPulling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingModel, setLoadingModel] = useState<string | null>(null);
  const [unloadingModel, setUnloadingModel] = useState<string | null>(null);
  const [savingSuggModel, setSavingSuggModel] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const d = await getAdminOllama().catch(() => null);
    if (d) setData(d);
    return d;
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const startLoadingPoll = (name: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    setLoadingModel(name);
    let attempts = 0;
    pollRef.current = setInterval(async () => {
      attempts++;
      const d = await getAdminOllama().catch(() => null);
      if (!d) return;
      setData(d);
      const isLoaded = (d.loaded_names as string[] || []).includes(name);
      if (isLoaded || attempts >= 30) {
        clearInterval(pollRef.current!);
        pollRef.current = null;
        setLoadingModel(null);
      }
    }, 2000);
  };

  const handleLoad = async (name: string) => {
    setError(null);
    try {
      await loadOllamaModel(name);
      startLoadingPoll(name);
    } catch (err: any) {
      setError(err.message || "Failed to load model");
    }
  };

  const handleUnload = async (name: string) => {
    setError(null);
    setUnloadingModel(name);
    try {
      await unloadOllamaModel(name);
      await load();
    } catch (err: any) {
      setError(err.message || "Failed to unload model");
    } finally {
      setUnloadingModel(null);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`Remove model "${name}" from the server? This cannot be undone.`)) return;
    setError(null);
    try {
      await deleteOllamaModel(name);
      load();
    } catch (err: any) {
      setError(err.message || "Failed to delete model");
    }
  };

  const handlePull = async () => {
    if (!pullName.trim()) return;
    setPulling(true);
    setPullStatus("Starting pull...");
    setError(null);
    try {
      for await (const progress of streamOllamaPull(pullName.trim())) {
        if (progress.status === "error") {
          setError(progress.error || "Pull failed");
          break;
        }
        if (progress.total && progress.completed) {
          const pct = Math.round((progress.completed / progress.total) * 100);
          setPullStatus(`${progress.status} — ${pct}%`);
        } else {
          setPullStatus(progress.status || "Pulling...");
        }
      }
      setPullName("");
      load();
    } catch (err: any) {
      setError(err.message || "Pull failed");
    } finally {
      setPulling(false);
      setPullStatus("");
    }
  };

  if (!data) return <p>Loading...</p>;

  const configuredModel: string = data.configured_model || "";
  const loadedNames: string[] = data.loaded_names || [];
  const stats = data.inference_stats || {};
  const contextWindow: number | null = data.context_window ?? null;
  const contextUsed: number = (stats.prompt_tokens || 0) + (stats.completion_tokens || 0);
  const tokensPerSec: number | null = stats.tokens_per_sec ?? null;

  const contextLabel = contextWindow
    ? `${contextUsed.toLocaleString()} / ${Math.round(contextWindow / 1000)}k`
    : contextUsed > 0 ? `${contextUsed.toLocaleString()} tokens` : "—";

  const activeModel = loadedNames.length > 0 ? loadedNames[0] : null;

  return (
    <div>
      {error && (
        <div className="error-banner" style={{ marginBottom: "1rem" }}>{error}</div>
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-value">{data.ollama?.status === "ok" ? "Connected" : "Offline"}</div>
          <div className="stat-label">Ollama Status</div>
        </div>
        <div className="stat-card">
          <div className="stat-value" style={{ fontSize: contextWindow ? "20px" : "28px" }}>{contextLabel}</div>
          <div className="stat-label">Context (last response)</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{tokensPerSec != null ? tokensPerSec : "—"}</div>
          <div className="stat-label">Tokens / sec</div>
        </div>
      </div>

      {/* Active model monitor */}
      <div style={{ margin: "1.5rem 0" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>Active Model for Inference</h4>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", padding: "10px 14px", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "6px" }}>
          {loadingModel ? (
            <>
              <span style={{ fontWeight: 600 }}>{loadingModel}</span>
              <span style={{ color: "#f59e0b", fontSize: "0.85rem" }}>Loading into memory...</span>
            </>
          ) : activeModel ? (
            <>
              <span style={{ fontWeight: 600 }}>{activeModel}</span>
              <span style={{ color: "var(--success)", fontSize: "0.85rem" }}>Loaded</span>
            </>
          ) : (
            <span style={{ color: "var(--text-muted)" }}>No model loaded</span>
          )}
        </div>
      </div>

      {/* Suggestion model selector */}
      <div style={{ margin: "1.5rem 0" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>Suggestion Generation Model</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: "0 0 0.5rem" }}>
          Used to generate suggested questions when building the Demo KB index. Can be a larger, slower model for higher quality.
        </p>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <select
            value={data.suggestion_model || ""}
            onChange={async (e) => {
              const name = e.target.value;
              if (!name) return;
              setSavingSuggModel(true);
              setError(null);
              try {
                await setSuggestionModel(name);
                setData((prev: any) => ({ ...prev, suggestion_model: name }));
              } catch (err: any) {
                setError(err.message || "Failed to set suggestion model");
              } finally {
                setSavingSuggModel(false);
              }
            }}
            disabled={savingSuggModel}
            style={{
              padding: "8px 12px",
              background: "var(--bg-card)",
              color: "var(--text)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              minWidth: "250px",
            }}
          >
            {data.models?.map((m: any) => (
              <option key={m.name} value={m.name}>{m.name}</option>
            ))}
          </select>
          {savingSuggModel && (
            <span style={{ color: "#f59e0b", fontSize: "0.85rem" }}>Saving...</span>
          )}
        </div>
      </div>

      {/* Pull new model */}
      <div style={{ margin: "1.5rem 0" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>Pull Model</h4>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <input
            placeholder="e.g. llama3.2, mistral, gemma3"
            value={pullName}
            onChange={(e) => setPullName(e.target.value)}
            disabled={pulling}
            onKeyDown={(e) => e.key === "Enter" && handlePull()}
            style={{ padding: "8px 12px", background: "var(--bg-card)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px", minWidth: "250px" }}
          />
          <button className="btn btn-primary" onClick={handlePull} disabled={pulling || !pullName.trim()}>
            {pulling ? "Pulling..." : "Pull"}
          </button>
          {pullStatus && (
            <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>{pullStatus}</span>
          )}
        </div>
      </div>

      {/* Model list with load/unload/remove buttons */}
      {data.models?.length > 0 && (
        <>
          <h4 style={{ marginBottom: "0.5rem" }}>Installed Models</h4>
          <table className="admin-table">
            <thead><tr><th>Model</th><th>Size</th><th>Modified</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {data.models.map((m: any) => {
                const isLoaded = loadedNames.includes(m.name);
                const isCurrentlyLoading = loadingModel === m.name;
                const isCurrentlyUnloading = unloadingModel === m.name;
                return (
                  <tr key={m.name}>
                    <td style={{ fontWeight: isLoaded ? 600 : 400 }}>{m.name}</td>
                    <td>{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : "-"}</td>
                    <td>{m.modified_at ? new Date(m.modified_at).toLocaleDateString() : "-"}</td>
                    <td>
                      {isCurrentlyLoading && (
                        <span style={{ color: "#f59e0b", fontSize: "0.8rem" }}>loading...</span>
                      )}
                      {isCurrentlyUnloading && (
                        <span style={{ color: "#f59e0b", fontSize: "0.8rem" }}>unloading...</span>
                      )}
                      {!isCurrentlyLoading && !isCurrentlyUnloading && isLoaded && (
                        <span style={{ color: "var(--success)", fontSize: "0.8rem" }}>active</span>
                      )}
                      {!isCurrentlyLoading && !isCurrentlyUnloading && !isLoaded && (
                        <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>idle</span>
                      )}
                    </td>
                    <td style={{ display: "flex", gap: "0.4rem", justifyContent: "flex-end" }}>
                      {!isLoaded && !isCurrentlyLoading && (
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => handleLoad(m.name)}
                          disabled={!!loadingModel}
                          title="Load into memory for inference"
                        >
                          Load
                        </button>
                      )}
                      {isLoaded && !isCurrentlyUnloading && (
                        <button
                          className="btn btn-sm"
                          onClick={() => handleUnload(m.name)}
                          title="Unload from memory"
                          style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)" }}
                        >
                          Unload
                        </button>
                      )}
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleDelete(m.name)}
                        disabled={isLoaded}
                        title={isLoaded ? "Unload the model first" : "Remove this model"}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ── Utility ───────────────────────────────────────────────────────────────────

function ms(val: number | null | undefined, fallback = "—"): string {
  if (val == null) return fallback;
  if (val >= 1000) return `${(val / 1000).toFixed(2)}s`;
  return `${val}ms`;
}

function PromptCell({ text }: { text: string }) {
  return (
    <span title={text} style={{ cursor: "default" }}>
      {text.length > 60 ? text.slice(0, 60) + "…" : text}
    </span>
  );
}

// ── Performance Tab ───────────────────────────────────────────────────────────

function PerformanceTab() {
  const [entries, setEntries] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [selected, setSelected] = useState<any | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const load = useCallback((p = 1) => {
    getPerfLog(p, 20).then((d) => {
      setEntries(d.entries ?? []);
      setTotal(d.total ?? 0);
      setPage(d.page ?? 1);
      setTotalPages(d.total_pages ?? 1);
    }).catch(() => {});
  }, []);

  useEffect(() => { load(1); }, [load]);

  const handleSelect = async (entry: any) => {
    if (selected?.id === entry.id) {
      setSelected(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const detail = await getPerfEntry(entry.id);
      setSelected(detail);
    } catch {
      setSelected(entry);
    } finally {
      setLoadingDetail(false);
    }
  };

  const thinking_ms = (e: any): number | null => {
    if (!e.user_ttft_ms || !e.ollama_connect_ms) return null;
    const v = e.user_ttft_ms - (e.search_ms ?? 0) - (e.prompt_build_ms ?? 0) - e.ollama_connect_ms;
    return v > 0 ? v : null;
  };

  const total_ms = (e: any): number | null => {
    if (e.search_ms == null && e.stream_total_ms == null) return null;
    return (e.search_ms ?? 0) + (e.prompt_build_ms ?? 0) + (e.stream_total_ms ?? 0);
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          Rolling window — {total} of 100 max entries
        </span>
        <button className="btn btn-sm" onClick={() => load(page)}>Refresh</button>
      </div>

      {entries.length === 0 ? (
        <p style={{ color: "var(--text-muted)" }}>No prompts logged yet. Send a chat message to populate this log.</p>
      ) : (
        <>
          <div style={{ overflowX: "auto" }}>
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>User</th>
                  <th>Prompt</th>
                  <th title="Search + prompt build time">Pre-LLM</th>
                  <th title="Time to first user-visible text token">TTFT</th>
                  <th title="Time model spent generating thinking tokens">Thinking</th>
                  <th title="Total Ollama stream duration">Gen</th>
                  <th title="Total end-to-end (search + prompt + gen)">Total</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => {
                  const isSelected = selected?.id === e.id;
                  const thinkMs = thinking_ms(e);
                  return (
                    <React.Fragment key={e.id}>
                      <tr
                        style={{
                          cursor: "pointer",
                          background: isSelected ? "color-mix(in srgb, var(--accent) 8%, var(--bg-card))" : undefined,
                          opacity: e.refused ? 0.55 : 1,
                        }}
                        onClick={() => handleSelect(e)}
                      >
                        <td style={{ whiteSpace: "nowrap", fontSize: "0.8rem" }}>
                          {new Date(e.timestamp).toLocaleTimeString()}
                          <div style={{ color: "var(--text-muted)", fontSize: "0.7rem" }}>
                            {new Date(e.timestamp).toLocaleDateString()}
                          </div>
                        </td>
                        <td style={{ fontSize: "0.85rem" }}>{e.user_name ?? <span style={{ color: "var(--text-muted)" }}>anon</span>}</td>
                        <td style={{ maxWidth: 240 }}>
                          <PromptCell text={e.prompt} />
                          {e.refused ? <span style={{ marginLeft: 6, fontSize: "0.7rem", color: "#f59e0b" }}>refused</span> : null}
                        </td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                          {ms((e.search_ms ?? 0) + (e.prompt_build_ms ?? 0))}
                        </td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                          {ms(e.user_ttft_ms)}
                        </td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: thinkMs ? "var(--text-muted)" : undefined }}>
                          {ms(thinkMs)}
                        </td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                          {ms(e.stream_total_ms)}
                        </td>
                        <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                          {ms(total_ms(e))}
                        </td>
                        <td>
                          <span style={{ color: "var(--text-muted)", fontSize: "0.75rem" }}>
                            {isSelected ? "▲" : "▼"}
                          </span>
                        </td>
                      </tr>
                      {isSelected && (
                        <tr>
                          <td colSpan={9} style={{ padding: 0 }}>
                            <PerfDetail entry={selected} loading={loadingDetail} thinkMs={thinkMs} totalMs={total_ms(e)} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginTop: "1rem" }}>
              <button className="btn btn-sm" disabled={page <= 1} onClick={() => load(page - 1)}>← Prev</button>
              <span style={{ padding: "4px 8px", color: "var(--text-muted)", fontSize: "0.85rem" }}>
                Page {page} / {totalPages}
              </span>
              <button className="btn btn-sm" disabled={page >= totalPages} onClick={() => load(page + 1)}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function PerfDetail({ entry, loading, thinkMs, totalMs }: {
  entry: any;
  loading: boolean;
  thinkMs: number | null;
  totalMs: number | null;
}) {
  if (loading) {
    return (
      <div style={{ padding: "1rem 1.5rem", background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
        Loading…
      </div>
    );
  }

  const row = (label: string, value: ReactNode) => (
    <div style={{ display: "flex", gap: "1rem", padding: "4px 0", borderBottom: "1px solid color-mix(in srgb, var(--border) 40%, transparent)" }}>
      <span style={{ width: 160, flexShrink: 0, color: "var(--text-muted)", fontSize: "0.82rem" }}>{label}</span>
      <span style={{ fontSize: "0.85rem", wordBreak: "break-word" }}>{value}</span>
    </div>
  );

  return (
    <div style={{ padding: "1rem 1.5rem", background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
      {/* Timing breakdown */}
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {[
          { label: "Search", val: entry.search_ms, color: "#60a5fa" },
          { label: "Prompt build", val: entry.prompt_build_ms, color: "#818cf8" },
          { label: "Ollama connect", val: entry.ollama_connect_ms, color: "#a78bfa" },
          { label: "Thinking", val: thinkMs, color: "#f59e0b" },
          { label: "TTFT (user)", val: entry.user_ttft_ms, color: "#34d399" },
          { label: "Gen complete", val: entry.stream_total_ms, color: "#f472b6" },
          { label: "Total", val: totalMs, color: "var(--text)", bold: true },
        ].map(({ label, val, color, bold }) => (
          <div key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center", minWidth: 80 }}>
            <span style={{ fontSize: "1.1rem", fontWeight: bold ? 700 : 500, color, fontVariantNumeric: "tabular-nums" }}>
              {val != null ? (val >= 1000 ? `${(val / 1000).toFixed(2)}s` : `${val}ms`) : "—"}
            </span>
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: 2 }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Metadata */}
      <div style={{ marginBottom: "1rem" }}>
        {row("User", entry.user_name ?? <span style={{ color: "var(--text-muted)" }}>anonymous</span>)}
        {row("Mode", entry.mode)}
        {row("Refused", entry.refused ? "Yes" : "No")}
        {row("Timestamp", new Date(entry.timestamp).toLocaleString())}
      </div>

      {/* Prompt */}
      <div style={{ marginBottom: "1rem" }}>
        <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Prompt</div>
        <div style={{ padding: "8px 12px", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 6, fontSize: "0.875rem", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {entry.prompt}
        </div>
      </div>

      {/* Thoughts */}
      {entry.thoughts && (
        <div style={{ marginBottom: "1rem" }}>
          <div style={{ fontSize: "0.75rem", color: "#f59e0b", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Thinking</div>
          <div style={{ padding: "8px 12px", background: "color-mix(in srgb, #f59e0b 6%, var(--bg-card))", border: "1px solid color-mix(in srgb, #f59e0b 20%, var(--border))", borderRadius: 6, fontSize: "0.82rem", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 300, overflowY: "auto", color: "var(--text-muted)" }}>
            {entry.thoughts}
          </div>
        </div>
      )}

      {/* Response */}
      {entry.response && (
        <div>
          <div style={{ fontSize: "0.75rem", color: "var(--success)", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.05em" }}>Response</div>
          <div style={{ padding: "8px 12px", background: "color-mix(in srgb, var(--success) 4%, var(--bg-card))", border: "1px solid color-mix(in srgb, var(--success) 20%, var(--border))", borderRadius: 6, fontSize: "0.875rem", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 400, overflowY: "auto" }}>
            {entry.response}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Configuration Tab ─────────────────────────────────────────────────────────

const CTX_PRESETS = [
  { label: "2k", value: 2048 },
  { label: "4k", value: 4096 },
  { label: "8k", value: 8192 },
  { label: "16k", value: 16384 },
  { label: "32k", value: 32768 },
  { label: "64k", value: 65536 },
  { label: "128k", value: 131072 },
];

function ConfigurationTab() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Context window
  const [numCtx, setNumCtx] = useState(4096);
  const [numCtxInput, setNumCtxInput] = useState("4096");
  const [reloading, setReloading] = useState(false);

  // System prompt
  const [systemPrompt, setSystemPrompt] = useState("");
  const [systemPromptDraft, setSystemPromptDraft] = useState("");

  // Rules
  const [systemRules, setSystemRules] = useState("");
  const [systemRulesDraft, setSystemRulesDraft] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    getAdminConfig()
      .then((d) => {
        setNumCtx(d.num_ctx ?? 4096);
        setNumCtxInput(String(d.num_ctx ?? 4096));
        setSystemPrompt(d.system_prompt ?? "");
        setSystemPromptDraft(d.system_prompt ?? "");
        setSystemRules(d.system_rules ?? "");
        setSystemRulesDraft(d.system_rules ?? "");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const flash = (msg: string) => {
    setSuccess(msg);
    setTimeout(() => setSuccess(null), 3000);
  };

  const handleSaveCtx = async () => {
    const val = parseInt(numCtxInput, 10);
    if (isNaN(val) || val < 512) {
      setError("Context window must be at least 512 tokens.");
      return;
    }
    setError(null);
    setSaving("ctx");
    try {
      const res = await updateAdminConfig({ num_ctx: val });
      setNumCtx(res.num_ctx);
      setNumCtxInput(String(res.num_ctx));
      if (res.reloading) {
        setReloading(true);
        flash(`Context window set to ${res.num_ctx.toLocaleString()} — model is reloading…`);
        setTimeout(() => setReloading(false), 8000);
      } else {
        flash(`Context window saved: ${res.num_ctx.toLocaleString()} tokens`);
      }
    } catch (e: any) {
      setError(e.message || "Failed to save context window");
    } finally {
      setSaving(null);
    }
  };

  const handleSavePrompt = async () => {
    setError(null);
    setSaving("prompt");
    try {
      await updateAdminConfig({ system_prompt: systemPromptDraft });
      setSystemPrompt(systemPromptDraft);
      flash("System prompt saved.");
    } catch (e: any) {
      setError(e.message || "Failed to save system prompt");
    } finally {
      setSaving(null);
    }
  };

  const handleResetPrompt = async () => {
    setError(null);
    setSaving("prompt");
    try {
      await updateAdminConfig({ system_prompt: "" });
      setSystemPrompt("");
      setSystemPromptDraft("");
      flash("System prompt reset to built-in default.");
    } catch (e: any) {
      setError(e.message || "Failed to reset system prompt");
    } finally {
      setSaving(null);
    }
  };

  const handleSaveRules = async () => {
    setError(null);
    setSaving("rules");
    try {
      await updateAdminConfig({ system_rules: systemRulesDraft });
      setSystemRules(systemRulesDraft);
      flash("Rules saved.");
    } catch (e: any) {
      setError(e.message || "Failed to save rules");
    } finally {
      setSaving(null);
    }
  };

  const sectionStyle: React.CSSProperties = {
    padding: "1.25rem 1.5rem",
    background: "var(--bg-card)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    marginBottom: "1.5rem",
  };

  const labelStyle: React.CSSProperties = {
    display: "block",
    fontSize: "0.8rem",
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: "var(--text-muted)",
    marginBottom: "0.5rem",
  };

  const textareaStyle: React.CSSProperties = {
    width: "100%",
    minHeight: 140,
    padding: "10px 12px",
    background: "var(--bg)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    fontFamily: "monospace",
    fontSize: "0.85rem",
    resize: "vertical",
    boxSizing: "border-box",
  };

  if (loading) return <p>Loading…</p>;

  return (
    <div style={{ maxWidth: 780 }}>
      {error && (
        <div className="error-banner" style={{ marginBottom: "1rem" }}>{error}</div>
      )}
      {success && (
        <div
          style={{
            marginBottom: "1rem",
            padding: "10px 14px",
            background: "color-mix(in srgb, var(--success) 12%, var(--bg-card))",
            border: "1px solid color-mix(in srgb, var(--success) 30%, var(--border))",
            borderRadius: "6px",
            color: "var(--success)",
            fontSize: "0.9rem",
          }}
        >
          {success}
        </div>
      )}

      {/* ── Context Window ── */}
      <div style={sectionStyle}>
        <h4 style={{ margin: "0 0 0.75rem" }}>Context Window</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: "0 0 1rem" }}>
          Number of tokens the loaded model keeps in its attention window. A larger value allows
          longer conversations but requires more GPU/CPU memory. Saving will unload and reload
          the model in Ollama to apply the new size.
        </p>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          {CTX_PRESETS.map((p) => (
            <button
              key={p.value}
              className={`btn btn-sm${numCtxInput === String(p.value) ? " btn-primary" : ""}`}
              style={numCtxInput !== String(p.value) ? { background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text)" } : {}}
              onClick={() => setNumCtxInput(String(p.value))}
            >
              {p.label}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <input
            type="number"
            value={numCtxInput}
            min={512}
            step={512}
            onChange={(e) => setNumCtxInput(e.target.value)}
            style={{ width: 120, padding: "7px 10px", background: "var(--bg)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px" }}
          />
          <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>tokens</span>
          <button
            className="btn btn-primary"
            onClick={handleSaveCtx}
            disabled={saving === "ctx" || numCtxInput === String(numCtx)}
          >
            {saving === "ctx" ? "Saving…" : "Save & Reload Model"}
          </button>
          {reloading && (
            <span style={{ color: "#f59e0b", fontSize: "0.85rem" }}>Reloading model…</span>
          )}
        </div>

        <div style={{ marginTop: "0.6rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Current: <strong>{numCtx.toLocaleString()}</strong> tokens
          {numCtx >= 1024 ? ` (${Math.round(numCtx / 1024)}k)` : ""}
        </div>
      </div>

      {/* ── System Prompt ── */}
      <div style={sectionStyle}>
        <h4 style={{ margin: "0 0 0.4rem" }}>System Prompt</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: "0 0 0.75rem" }}>
          Overrides the built-in system prompt sent to the model on every request.
          Leave blank to use the default prompt.
        </p>
        <label style={labelStyle}>Custom system prompt</label>
        <textarea
          style={textareaStyle}
          value={systemPromptDraft}
          onChange={(e) => setSystemPromptDraft(e.target.value)}
          placeholder="Leave blank to use the built-in default prompt…"
          spellCheck={false}
        />
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.75rem" }}>
          <button
            className="btn btn-primary"
            onClick={handleSavePrompt}
            disabled={saving === "prompt" || systemPromptDraft === systemPrompt}
          >
            {saving === "prompt" ? "Saving…" : "Save Prompt"}
          </button>
          {systemPrompt && (
            <button
              className="btn btn-sm"
              style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
              onClick={handleResetPrompt}
              disabled={saving === "prompt"}
            >
              Reset to default
            </button>
          )}
        </div>
        {!systemPrompt && (
          <div style={{ marginTop: "0.5rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Using built-in default prompt.
          </div>
        )}
      </div>

      {/* ── Rules ── */}
      <div style={sectionStyle}>
        <h4 style={{ margin: "0 0 0.4rem" }}>Additional Rules</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.875rem", margin: "0 0 0.75rem" }}>
          Appended after the system prompt (whether default or custom). Useful for adding
          extra constraints or persona instructions without replacing the whole prompt.
        </p>
        <label style={labelStyle}>Rules / extra instructions</label>
        <textarea
          style={textareaStyle}
          value={systemRulesDraft}
          onChange={(e) => setSystemRulesDraft(e.target.value)}
          placeholder={"e.g.\n- Always respond in British English.\n- Never mention competitor products."}
          spellCheck={false}
        />
        <div style={{ display: "flex", gap: "0.75rem", marginTop: "0.75rem" }}>
          <button
            className="btn btn-primary"
            onClick={handleSaveRules}
            disabled={saving === "rules" || systemRulesDraft === systemRules}
          >
            {saving === "rules" ? "Saving…" : "Save Rules"}
          </button>
          {systemRules && (
            <button
              className="btn btn-sm"
              style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
              onClick={async () => {
                setSystemRulesDraft("");
                setSaving("rules");
                try {
                  await updateAdminConfig({ system_rules: "" });
                  setSystemRules("");
                  flash("Rules cleared.");
                } catch (e: any) {
                  setError(e.message);
                } finally {
                  setSaving(null);
                }
              }}
              disabled={saving === "rules"}
            >
              Clear rules
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function DemoKBTab() {
  const [docs, setDocs] = useState<any[]>([]);
  const [status, setStatus] = useState<any>({ job: { status: "idle", error: null }, total_chunks: 0, categories: {} });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Suggestions state
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [newSuggestion, setNewSuggestion] = useState("");
  const [editingSuggIdx, setEditingSuggIdx] = useState<number | null>(null);
  const [editingSuggText, setEditingSuggText] = useState("");

  // Q&A / STAR state
  const [qaItems, setQaItems] = useState<any[]>([]);
  const [showQaForm, setShowQaForm] = useState(false);
  const [editingQaId, setEditingQaId] = useState<string | null>(null);
  const [qaForm, setQaForm] = useState<any>({ type: "qa", question: "", answer: "", situation: "", task: "", action: "", result: "" });

  const loadDocs = useCallback(() => {
    getDemoDocuments().then((d) => setDocs(d.documents)).catch(() => {});
  }, []);

  const loadStatus = useCallback(() => {
    getDemoStatus().then(setStatus).catch(() => {});
  }, []);

  const loadSuggestions = useCallback(() => {
    getDemoSuggestions().then((d) => setSuggestions(d.suggestions || [])).catch(() => {});
  }, []);

  const loadQA = useCallback(() => {
    getDemoQA().then((d) => setQaItems(d.items || [])).catch(() => {});
  }, []);

  useEffect(() => {
    loadDocs();
    loadStatus();
    loadSuggestions();
    loadQA();
  }, [loadDocs, loadStatus, loadSuggestions, loadQA]);

  useEffect(() => {
    if (status.job?.status === "running") {
      pollRef.current = setInterval(() => {
        getDemoStatus().then((s) => {
          setStatus(s);
          if (s.job?.status !== "running" && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            loadSuggestions();
          }
        }).catch(() => {});
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status.job?.status, loadSuggestions]);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of files) {
        await uploadDemoDocument(file);
      }
      loadDocs();
    } catch (err: any) {
      setError(err.message || "Upload failed");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (filename: string) => {
    if (!confirm(`Delete "${filename}" from demo KB?`)) return;
    try {
      await deleteDemoDocument(filename);
      loadDocs();
    } catch (err: any) {
      setError(err.message || "Delete failed");
    }
  };

  const handleBuild = async () => {
    setError(null);
    try {
      await buildDemoIndex();
      setStatus((s: any) => ({ ...s, job: { status: "running", error: null } }));
    } catch (err: any) {
      setError(err.message || "Build failed");
    }
  };

  // Suggestion handlers
  const handleAddSuggestion = async () => {
    if (!newSuggestion.trim()) return;
    try {
      const res = await addDemoSuggestion(newSuggestion.trim());
      setSuggestions(res.suggestions);
      setNewSuggestion("");
    } catch (err: any) {
      setError(err.message || "Failed to add suggestion");
    }
  };

  const handleDeleteSuggestion = async (idx: number) => {
    try {
      const res = await deleteDemoSuggestion(idx);
      setSuggestions(res.suggestions);
    } catch (err: any) {
      setError(err.message || "Failed to delete suggestion");
    }
  };

  const handleSaveSuggestionEdit = async (idx: number) => {
    if (!editingSuggText.trim()) return;
    const updated = [...suggestions];
    updated[idx] = editingSuggText.trim();
    try {
      const res = await updateDemoSuggestions(updated);
      setSuggestions(res.suggestions);
      setEditingSuggIdx(null);
      setEditingSuggText("");
    } catch (err: any) {
      setError(err.message || "Failed to update suggestion");
    }
  };

  // Q&A form helpers
  const resetQaForm = () => {
    setQaForm({ type: "qa", question: "", answer: "", situation: "", task: "", action: "", result: "" });
    setShowQaForm(false);
    setEditingQaId(null);
  };

  const handleSaveQa = async () => {
    if (!qaForm.question.trim()) {
      setError("Question is required");
      return;
    }
    try {
      if (editingQaId) {
        const res = await updateDemoQA(editingQaId, qaForm);
        setQaItems(res.items);
      } else {
        const res = await createDemoQA(qaForm);
        setQaItems(res.items);
      }
      resetQaForm();
    } catch (err: any) {
      setError(err.message || "Failed to save Q&A item");
    }
  };

  const handleEditQa = (item: any) => {
    setEditingQaId(item.id);
    setQaForm({
      type: item.type,
      question: item.question || "",
      answer: item.answer || "",
      situation: item.situation || "",
      task: item.task || "",
      action: item.action || "",
      result: item.result || "",
    });
    setShowQaForm(true);
  };

  const handleDeleteQa = async (id: string) => {
    if (!confirm("Delete this Q&A item?")) return;
    try {
      const res = await deleteDemoQA(id);
      setQaItems(res.items);
    } catch (err: any) {
      setError(err.message || "Failed to delete Q&A item");
    }
  };

  const jobStatus = status.job?.status ?? "idle";
  const totalChunks = status.total_chunks ?? 0;
  const categories: Record<string, number> = status.categories ?? {};

  const sectionStyle: React.CSSProperties = {
    padding: "1.25rem 1.5rem",
    background: "var(--bg-card)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    marginBottom: "1.5rem",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    padding: "8px 12px",
    background: "var(--bg)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    fontSize: "0.875rem",
    boxSizing: "border-box",
  };

  const textareaStyle: React.CSSProperties = {
    ...inputStyle,
    minHeight: 80,
    fontFamily: "inherit",
    resize: "vertical",
  };

  return (
    <div>
      <p style={{ marginBottom: "1rem", color: "var(--text-muted)" }}>
        Upload documents here to power the public <strong>Ask Me Anything</strong> chat. After uploading, click
        <strong> Build Index</strong> to make them searchable.
      </p>

      {error && (
        <div className="error-banner" style={{ marginBottom: "1rem" }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 8, background: "none", border: "none", color: "inherit", cursor: "pointer", fontWeight: 700 }}>x</button>
        </div>
      )}

      {/* ── Upload area ── */}
      <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "1.5rem" }}>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.txt,.docx,.pptx,.csv"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
        <button
          className="btn btn-primary"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? "Uploading…" : "Upload Documents"}
        </button>
        <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
          PDF, TXT, DOCX, PPTX, CSV — max 50 MB each
        </span>
      </div>

      {/* ── Document list ── */}
      {docs.length > 0 ? (
        <table className="admin-table" style={{ marginBottom: "1.5rem" }}>
          <thead>
            <tr><th>Filename</th><th>Size</th><th>Modified</th><th></th></tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.filename}>
                <td>{d.filename}</td>
                <td>{d.size_bytes > 1024 * 1024
                  ? `${(d.size_bytes / (1024 * 1024)).toFixed(1)} MB`
                  : `${Math.round(d.size_bytes / 1024)} KB`}
                </td>
                <td>{new Date(d.modified).toLocaleDateString()}</td>
                <td>
                  <button className="btn btn-sm btn-danger" onClick={() => handleDelete(d.filename)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--text-muted)", marginBottom: "1.5rem" }}>
          No documents uploaded yet.
        </p>
      )}

      {/* ── Index controls ── */}
      <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginBottom: "1.5rem" }}>
        <button
          className="btn btn-primary"
          onClick={handleBuild}
          disabled={jobStatus === "running" || docs.length === 0}
        >
          {jobStatus === "running" ? "Building…" : "Build Index"}
        </button>
        <span style={{
          color: jobStatus === "complete" ? "var(--success)"
            : jobStatus === "failed" ? "var(--danger)"
            : jobStatus === "running" ? "#f59e0b"
            : "var(--text-muted)",
          fontSize: "0.9rem",
        }}>
          {jobStatus === "idle" && "Not indexed"}
          {jobStatus === "complete" && `Index up to date — ${totalChunks} chunks`}
          {jobStatus === "failed" && `Failed: ${status.job?.error || "unknown error"}`}
        </span>
      </div>

      {/* ── Granular build progress ── */}
      {jobStatus === "running" && (() => {
        const step = status.job?.step || "indexing";
        const detail = status.job?.detail || "";
        const steps = [
          { key: "indexing", label: "Indexing documents" },
          { key: "generating", label: "Generating questions" },
          { key: "validating", label: "Validating questions" },
        ];
        const activeIdx = steps.findIndex((s) => s.key === step);
        return (
          <div style={{ marginBottom: "1.5rem", padding: "12px 16px", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: "8px" }}>
            <div style={{ display: "flex", gap: "20px", marginBottom: detail ? "8px" : 0 }}>
              {steps.map((s, i) => (
                <div key={s.key} style={{
                  display: "flex", alignItems: "center", gap: "6px", fontSize: "13px",
                  color: i < activeIdx ? "var(--success)" : i === activeIdx ? "#f59e0b" : "var(--text-muted)",
                  opacity: i > activeIdx ? 0.4 : 1,
                }}>
                  <span style={{
                    width: 8, height: 8, borderRadius: "50%", background: "currentColor", flexShrink: 0,
                    animation: i === activeIdx ? "pulse-dot 1.2s ease-in-out infinite" : "none",
                  }} />
                  {s.label}
                </div>
              ))}
            </div>
            {detail && (
              <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{detail}</div>
            )}
          </div>
        );
      })()}

      {/* ── Index Breakdown ── */}
      {Object.keys(categories).length > 0 && (
        <div style={{ marginBottom: "1.5rem" }}>
          <h4 style={{ marginBottom: "0.5rem" }}>Index Breakdown</h4>
          <div className="stats-grid">
            {Object.entries(categories).map(([cat, count]) => (
              <div className="stat-card" key={cat}>
                <div className="stat-value">{count as number}</div>
                <div className="stat-label">{cat}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Generated Suggested Questions ── */}
      <div style={sectionStyle}>
        <h4 style={{ margin: "0 0 0.4rem" }}>Generated Suggested Questions</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: "0 0 0.75rem" }}>
          These questions appear as conversation starters for visitors. They are regenerated each time you build the index;
          manual edits persist until the next rebuild.
        </p>

        {suggestions.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "0.75rem" }}>
            {suggestions.map((q, idx) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "center",
                  padding: "6px 10px",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "6px",
                  fontSize: "0.875rem",
                }}
              >
                {editingSuggIdx === idx ? (
                  <>
                    <input
                      value={editingSuggText}
                      onChange={(e) => setEditingSuggText(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleSaveSuggestionEdit(idx)}
                      style={{ ...inputStyle, flex: 1 }}
                      autoFocus
                    />
                    <button className="btn btn-sm btn-primary" onClick={() => handleSaveSuggestionEdit(idx)}>Save</button>
                    <button className="btn btn-sm" onClick={() => { setEditingSuggIdx(null); setEditingSuggText(""); }}
                      style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)" }}
                    >Cancel</button>
                  </>
                ) : (
                  <>
                    <span style={{ flex: 1 }}>{q}</span>
                    <button
                      className="btn btn-sm"
                      onClick={() => { setEditingSuggIdx(idx); setEditingSuggText(q); }}
                      style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)", padding: "2px 8px" }}
                      title="Edit"
                    >Edit</button>
                    <button
                      className="btn btn-sm btn-danger"
                      onClick={() => handleDeleteSuggestion(idx)}
                      style={{ padding: "2px 8px" }}
                      title="Remove"
                    >Del</button>
                  </>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginBottom: "0.75rem" }}>
            No suggestions yet. Build the index to generate them.
          </p>
        )}

        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            placeholder="Add a suggested question…"
            value={newSuggestion}
            onChange={(e) => setNewSuggestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddSuggestion()}
            style={{ ...inputStyle, flex: 1 }}
          />
          <button
            className="btn btn-primary btn-sm"
            onClick={handleAddSuggestion}
            disabled={!newSuggestion.trim()}
          >Add</button>
        </div>
      </div>

      {/* ── Default Q&A and STAR Stories ── */}
      <div style={sectionStyle}>
        <h4 style={{ margin: "0 0 0.4rem" }}>Default Q&A and STAR Stories</h4>
        <p style={{ color: "var(--text-muted)", fontSize: "0.85rem", margin: "0 0 0.75rem" }}>
          Curated question-answer pairs and behavioral STAR stories. These are injected into the index on each build
          and their questions are always included in suggestions.
        </p>

        {qaItems.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "1rem" }}>
            {qaItems.map((item) => (
              <div
                key={item.id}
                style={{
                  padding: "10px 14px",
                  background: "var(--bg)",
                  border: "1px solid var(--border)",
                  borderRadius: "6px",
                }}
              >
                <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start", marginBottom: "4px" }}>
                  <span style={{
                    fontSize: "0.7rem",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    flexShrink: 0,
                    background: item.type === "star"
                      ? "color-mix(in srgb, #f59e0b 15%, var(--bg-card))"
                      : "color-mix(in srgb, var(--accent) 15%, var(--bg-card))",
                    color: item.type === "star" ? "#f59e0b" : "var(--accent)",
                  }}>
                    {item.type === "star" ? "STAR" : "Q&A"}
                  </span>
                  <span style={{ flex: 1, fontWeight: 500, fontSize: "0.9rem" }}>{item.question}</span>
                  <button
                    className="btn btn-sm"
                    onClick={() => handleEditQa(item)}
                    style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)", padding: "2px 8px" }}
                  >Edit</button>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleDeleteQa(item.id)}
                    style={{ padding: "2px 8px" }}
                  >Del</button>
                </div>
                {item.type === "qa" && item.answer && (
                  <div style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginLeft: "3rem", whiteSpace: "pre-wrap" }}>
                    {item.answer.length > 200 ? item.answer.slice(0, 200) + "…" : item.answer}
                  </div>
                )}
                {item.type === "star" && (
                  <div style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginLeft: "3rem" }}>
                    {["situation", "task", "action", "result"].map((f) => item[f] ? (
                      <div key={f} style={{ marginTop: 2 }}>
                        <strong style={{ textTransform: "capitalize" }}>{f}:</strong>{" "}
                        {(item[f] as string).length > 120 ? (item[f] as string).slice(0, 120) + "…" : item[f]}
                      </div>
                    ) : null)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Add / Edit form */}
        {showQaForm ? (
          <div style={{ padding: "14px", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px" }}>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginBottom: "0.75rem" }}>
              <label style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-muted)" }}>Type:</label>
              <button
                className={`btn btn-sm${qaForm.type === "qa" ? " btn-primary" : ""}`}
                style={qaForm.type !== "qa" ? { background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)" } : {}}
                onClick={() => setQaForm((f: any) => ({ ...f, type: "qa" }))}
              >Q&A</button>
              <button
                className={`btn btn-sm${qaForm.type === "star" ? " btn-primary" : ""}`}
                style={qaForm.type !== "star" ? { background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)" } : {}}
                onClick={() => setQaForm((f: any) => ({ ...f, type: "star" }))}
              >STAR</button>
            </div>

            <div style={{ marginBottom: "0.5rem" }}>
              <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: 4 }}>Question</label>
              <input
                value={qaForm.question}
                onChange={(e) => setQaForm((f: any) => ({ ...f, question: e.target.value }))}
                placeholder="e.g. Tell me about a time you led a difficult project."
                style={inputStyle}
              />
            </div>

            {qaForm.type === "qa" ? (
              <div style={{ marginBottom: "0.5rem" }}>
                <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: 4 }}>Answer</label>
                <textarea
                  value={qaForm.answer}
                  onChange={(e) => setQaForm((f: any) => ({ ...f, answer: e.target.value }))}
                  placeholder="The curated answer..."
                  style={textareaStyle}
                />
              </div>
            ) : (
              <>
                {(["situation", "task", "action", "result"] as const).map((field) => (
                  <div key={field} style={{ marginBottom: "0.5rem" }}>
                    <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "var(--text-muted)", marginBottom: 4, textTransform: "capitalize" }}>{field}</label>
                    <textarea
                      value={qaForm[field]}
                      onChange={(e) => setQaForm((f: any) => ({ ...f, [field]: e.target.value }))}
                      placeholder={
                        field === "situation" ? "Describe the context and challenge..."
                          : field === "task" ? "What was your responsibility?"
                          : field === "action" ? "What specific steps did you take?"
                          : "What was the outcome?"
                      }
                      style={textareaStyle}
                    />
                  </div>
                ))}
              </>
            )}

            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
              <button className="btn btn-primary" onClick={handleSaveQa}>
                {editingQaId ? "Save Changes" : "Add Item"}
              </button>
              <button
                className="btn btn-sm"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text)" }}
                onClick={resetQaForm}
              >Cancel</button>
            </div>
          </div>
        ) : (
          <button
            className="btn btn-primary btn-sm"
            onClick={() => { resetQaForm(); setShowQaForm(true); }}
          >Add Q&A / STAR Story</button>
        )}
      </div>
    </div>
  );
}
