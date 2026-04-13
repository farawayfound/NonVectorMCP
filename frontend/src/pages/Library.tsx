import { useCallback, useEffect, useRef, useState } from "react";
import { useLibrary, type LibraryTask } from "../hooks/useLibrary";
import { getLibraryTask } from "../api/client";

type View = "list" | "detail";

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  crawling: "Crawling",
  synthesizing: "Synthesizing",
  review: "Ready for Review",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<string, string> = {
  queued: "var(--text-muted)",
  crawling: "var(--primary)",
  synthesizing: "var(--primary)",
  review: "#f59e0b",
  approved: "var(--success)",
  rejected: "var(--danger)",
  failed: "var(--danger)",
  cancelled: "var(--text-muted)",
};

function isActive(status: string) {
  return ["queued", "crawling", "synthesizing"].includes(status);
}

export function Library() {
  const {
    tasks, loading, submitting, error,
    refresh, submit, approve, reject, remove,
  } = useLibrary();

  const [view, setView] = useState<View>("list");
  const [prompt, setPrompt] = useState("");
  const [maxSources, setMaxSources] = useState(10);
  const [showOptions, setShowOptions] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryTask | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [approveResult, setApproveResult] = useState<any>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { refresh(); }, [refresh]);

  const handleSubmit = useCallback(async () => {
    if (!prompt.trim() || submitting) return;
    try {
      await submit(prompt.trim(), { max_sources: maxSources });
      setPrompt("");
    } catch {
      // error is set in hook
    }
  }, [prompt, maxSources, submitting, submit]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setView("detail");
    setDetailLoading(true);
    setApproveResult(null);
    try {
      const t = await getLibraryTask(id);
      setDetail(t);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleApprove = useCallback(async () => {
    if (!selectedId) return;
    try {
      const res = await approve(selectedId);
      setApproveResult(res);
      const t = await getLibraryTask(selectedId);
      setDetail(t);
    } catch {
      // shown via hook error
    }
  }, [selectedId, approve]);

  const handleReject = useCallback(async () => {
    if (!selectedId) return;
    await reject(selectedId);
    setView("list");
  }, [selectedId, reject]);

  const handleDelete = useCallback(async (id: string) => {
    await remove(id);
    if (selectedId === id) setView("list");
  }, [remove, selectedId]);

  // ── List view ──

  if (view === "list") {
    return (
      <div className="library-page">
        <div className="library-header">
          <h2>Library</h2>
          <p className="library-subtitle">
            Submit research prompts and let the worker crawl, scrape, and synthesize reports.
          </p>
        </div>

        <div className="library-input-section">
          <div className="library-input-row">
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Compile a report on the latest advancements in graph RAG..."
              rows={2}
              disabled={submitting}
            />
            <button
              className="btn btn-primary"
              onClick={handleSubmit}
              disabled={submitting || !prompt.trim()}
            >
              {submitting ? "Submitting..." : "Research"}
            </button>
          </div>
          <div className="library-options-row">
            <button
              className="library-options-toggle"
              onClick={() => setShowOptions(!showOptions)}
            >
              <span className={`chunking-chevron ${showOptions ? "open" : ""}`}>&#9654;</span>
              Options
            </button>
            {showOptions && (
              <div className="library-options-body">
                <label>
                  Max sources:
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={maxSources}
                    onChange={(e) => setMaxSources(Number(e.target.value))}
                  />
                </label>
              </div>
            )}
          </div>
        </div>

        {error && <div className="library-error">{error}</div>}

        <div className="library-task-list">
          {loading && tasks.length === 0 && (
            <p className="library-empty">Loading tasks...</p>
          )}
          {!loading && tasks.length === 0 && (
            <p className="library-empty">No research tasks yet. Submit a prompt above to get started.</p>
          )}
          {tasks.map((t) => (
            <div key={t.id} className="library-task-card" onClick={() => openDetail(t.id)}>
              <div className="library-task-info">
                <span className="library-task-prompt">{t.prompt}</span>
                <span className="library-task-meta">
                  {new Date(t.created_at).toLocaleString()}
                  {t.sources_found > 0 && ` \u00b7 ${t.sources_found} sources`}
                </span>
              </div>
              <div className="library-task-actions">
                <span
                  className={`library-status ${isActive(t.status) ? "active" : ""}`}
                  style={{ color: STATUS_COLORS[t.status] || "var(--text-muted)" }}
                >
                  {isActive(t.status) && <span className="library-status-dot" />}
                  {STATUS_LABELS[t.status] || t.status}
                </span>
                {["review", "approved", "rejected", "failed", "cancelled"].includes(t.status) && (
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={(e) => { e.stopPropagation(); handleDelete(t.id); }}
                    title="Delete"
                  >
                    &times;
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Detail / Review view ──

  return (
    <div className="library-page">
      <div className="library-detail-header">
        <button className="btn btn-sm" onClick={() => setView("list")}>&larr; Back</button>
        {detail && (
          <span
            className="library-status"
            style={{ color: STATUS_COLORS[detail.status] || "var(--text-muted)" }}
          >
            {STATUS_LABELS[detail.status] || detail.status}
          </span>
        )}
      </div>

      {detailLoading && <p className="library-empty">Loading...</p>}

      {detail && (
        <>
          <div className="library-detail-prompt">
            <h3>Research Prompt</h3>
            <p>{detail.prompt}</p>
          </div>

          {detail.sources && detail.sources.length > 0 && (
            <div className="library-detail-sources">
              <h4>Sources ({detail.sources.length})</h4>
              <ul>
                {detail.sources.map((s, i) => (
                  <li key={i}>
                    <a href={s.url} target="_blank" rel="noopener noreferrer">
                      {s.title || s.url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {detail.artifact && (
            <div className="library-detail-artifact">
              <h4>Generated Report</h4>
              <div className="library-artifact-content">
                <pre>{detail.artifact}</pre>
              </div>
            </div>
          )}

          {detail.error && (
            <div className="library-error">Error: {detail.error}</div>
          )}

          {approveResult && (
            <div className={`library-approve-result ${approveResult.status === "approved" ? "success" : ""}`}>
              {approveResult.status === "approved" && (
                <span>Approved and saved as <strong>{approveResult.filename}</strong>. Build your index from Workspace to include it in RAG.</span>
              )}
              {approveResult.status === "duplicate" && (
                <span>Duplicate detected (similarity {approveResult.similarity}) — already in your knowledge base.</span>
              )}
              {approveResult.status === "rejected_quality" && (
                <span>Quality gate rejected: {approveResult.reason}</span>
              )}
            </div>
          )}

          {detail.status === "review" && !approveResult && (
            <div className="library-review-actions">
              <button className="btn btn-primary" onClick={handleApprove}>
                Approve &amp; Add to Documents
              </button>
              <button className="btn btn-danger" onClick={handleReject}>
                Reject
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
