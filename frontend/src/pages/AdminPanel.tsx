import { useState, useEffect, useCallback, useRef } from "react";
import {
  getAdminStats,
  getAdminUsers,
  getInviteCodes,
  createInviteCode,
  deactivateInviteCode,
  getAdminActivity,
  getAdminOllama,
  setOllamaModel,
  deleteOllamaModel,
  streamOllamaPull,
  getDemoDocuments,
  deleteDemoDocument,
  uploadDemoDocument,
  buildDemoIndex,
  getDemoStatus,
} from "../api/client";
import type { InviteCode } from "../types";

type Tab = "overview" | "codes" | "users" | "activity" | "ollama" | "demokb";

const TAB_LABELS: Record<Tab, string> = {
  overview: "Overview",
  codes: "Codes",
  users: "Users",
  activity: "Activity",
  ollama: "Ollama",
  demokb: "Demo KB",
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

function CodesTab() {
  const [codes, setCodes] = useState<InviteCode[]>([]);
  const [label, setLabel] = useState("");
  const [maxUses, setMaxUses] = useState(0);

  const load = useCallback(() => {
    getInviteCodes().then((d) => setCodes(d.codes)).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    await createInviteCode({ label, max_uses: maxUses });
    setLabel("");
    setMaxUses(0);
    load();
  };

  const handleDeactivate = async (code: string) => {
    await deactivateInviteCode(code);
    load();
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
        <button className="btn btn-primary" onClick={handleCreate}>Create Code</button>
      </div>
      <table className="admin-table">
        <thead>
          <tr><th>Code</th><th>Label</th><th>Redemptions</th><th>Created</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {codes.map((c) => (
            <tr key={c.code}>
              <td className="monospace">{c.code}</td>
              <td>{c.label || "-"}</td>
              <td>{c.use_count}{c.max_uses > 0 ? `/${c.max_uses}` : ""}</td>
              <td>{new Date(c.created_at).toLocaleDateString()}</td>
              <td>{c.active ? "Active" : "Inactive"}</td>
              <td>
                {c.active ? (
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
  // Name of the model that was just selected but may not be in memory yet
  const [loadingModel, setLoadingModel] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    const d = await getAdminOllama().catch(() => null);
    if (d) setData(d);
    return d;
  }, []);

  useEffect(() => { load(); }, [load]);

  // Stop polling on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  // Poll /admin/ollama every 2 s after a model change until it appears in loaded_names
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

  const handleSetModel = async (name: string) => {
    setError(null);
    try {
      await setOllamaModel(name);
      setData((d: any) => ({ ...d, configured_model: name }));
      startLoadingPoll(name);
    } catch (err: any) {
      setError(err.message || "Failed to set model");
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

      {/* Active model selector */}
      <div style={{ margin: "1.5rem 0" }}>
        <h4 style={{ marginBottom: "0.5rem" }}>Active Model for Inference</h4>
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          <select
            value={configuredModel}
            onChange={(e) => handleSetModel(e.target.value)}
            style={{ padding: "8px 12px", background: "var(--bg-card)", color: "var(--text)", border: "1px solid var(--border)", borderRadius: "6px", minWidth: "250px" }}
          >
            {data.models?.map((m: any) => (
              <option key={m.name} value={m.name}>{m.name}</option>
            ))}
          </select>
          {loadingModel === configuredModel ? (
            <span style={{ color: "#f59e0b", fontSize: "0.85rem" }}>Loading into memory…</span>
          ) : loadedNames.includes(configuredModel) ? (
            <span style={{ color: "var(--success)", fontSize: "0.85rem" }}>Ready</span>
          ) : (
            <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>Not yet loaded</span>
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

      {/* Model list with remove button */}
      {data.models?.length > 0 && (
        <>
          <h4 style={{ marginBottom: "0.5rem" }}>Installed Models</h4>
          <table className="admin-table">
            <thead><tr><th>Model</th><th>Size</th><th>Modified</th><th></th></tr></thead>
            <tbody>
              {data.models.map((m: any) => {
                const isConfigured = m.name === configuredModel;
                const isLoaded = loadedNames.includes(m.name);
                const isCurrentlyLoading = loadingModel === m.name;
                return (
                  <tr key={m.name}>
                    <td>
                      {m.name}
                      {isCurrentlyLoading && (
                        <span style={{ marginLeft: "0.5rem", color: "#f59e0b", fontSize: "0.75rem" }}>loading…</span>
                      )}
                      {!isCurrentlyLoading && isLoaded && (
                        <span style={{ marginLeft: "0.5rem", color: "var(--success)", fontSize: "0.75rem" }}>active</span>
                      )}
                    </td>
                    <td>{m.size ? `${(m.size / 1e9).toFixed(1)} GB` : "-"}</td>
                    <td>{m.modified_at ? new Date(m.modified_at).toLocaleDateString() : "-"}</td>
                    <td>
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleDelete(m.name)}
                        disabled={isConfigured}
                        title={isConfigured ? "Cannot remove the active model" : "Remove this model"}
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

function DemoKBTab() {
  const [docs, setDocs] = useState<any[]>([]);
  const [status, setStatus] = useState<any>({ job: { status: "idle", error: null }, total_chunks: 0, categories: {} });
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDocs = useCallback(() => {
    getDemoDocuments().then((d) => setDocs(d.documents)).catch(() => {});
  }, []);

  const loadStatus = useCallback(() => {
    getDemoStatus().then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    loadDocs();
    loadStatus();
  }, [loadDocs, loadStatus]);

  // Poll for status while indexing is running
  useEffect(() => {
    if (status.job?.status === "running") {
      pollRef.current = setInterval(() => {
        getDemoStatus().then((s) => {
          setStatus(s);
          if (s.job?.status !== "running" && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }).catch(() => {});
      }, 2000);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [status.job?.status]);

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

  const jobStatus = status.job?.status ?? "idle";
  const totalChunks = status.total_chunks ?? 0;
  const categories: Record<string, number> = status.categories ?? {};

  return (
    <div>
      <p style={{ marginBottom: "1rem", color: "var(--text-muted)" }}>
        Upload documents here to power the public <strong>Ask Me Anything</strong> chat. After uploading, click
        <strong> Build Index</strong> to make them searchable.
      </p>

      {error && (
        <div className="error-banner" style={{ marginBottom: "1rem" }}>
          {error}
        </div>
      )}

      {/* Upload area */}
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

      {/* Document list */}
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

      {/* Index controls */}
      <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginBottom: "1.5rem" }}>
        <button
          className="btn btn-primary"
          onClick={handleBuild}
          disabled={jobStatus === "running" || docs.length === 0}
        >
          {jobStatus === "running" ? "Indexing…" : "Build Index"}
        </button>
        <span style={{
          color: jobStatus === "complete" ? "var(--success)"
            : jobStatus === "failed" ? "var(--danger)"
            : jobStatus === "running" ? "var(--warning)"
            : "var(--text-muted)",
          fontSize: "0.9rem",
        }}>
          {jobStatus === "idle" && "Not indexed"}
          {jobStatus === "running" && "Indexing in progress…"}
          {jobStatus === "complete" && `Index up to date — ${totalChunks} chunks`}
          {jobStatus === "failed" && `Failed: ${status.job?.error || "unknown error"}`}
        </span>
      </div>

      {/* Category breakdown */}
      {Object.keys(categories).length > 0 && (
        <div>
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
    </div>
  );
}
