import { useCallback, useEffect, useState } from "react";
import { useLibrary, type LibraryTask } from "../hooks/useLibrary";
import { getLibraryTask, getIndexEmailStatus } from "../api/client";

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

function canUserCancelTask(status: string) {
  return !["approved", "rejected", "cancelled"].includes(status);
}

export function Library() {
  const {
    tasks, loading, submitting, error,
    refresh, submit, approve, reject, remove, cancelSelected,
  } = useLibrary();

  const [view, setView] = useState<View>("list");
  const [prompt, setPrompt] = useState("");
  const [maxSources, setMaxSources] = useState(10);
  const [showOptions, setShowOptions] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<LibraryTask | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [approveResult, setApproveResult] = useState<any>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  // Confirm modal state
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmEmail, setConfirmEmail] = useState("");
  const [hasStoredEmail, setHasStoredEmail] = useState(false);
  const [confirmSubmitting, setConfirmSubmitting] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);

  const [selectedForCancel, setSelectedForCancel] = useState<Set<string>>(() => new Set());
  const [cancellingBulk, setCancellingBulk] = useState(false);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const allowed = new Set(
      tasks.filter((t) => canUserCancelTask(t.status)).map((t) => t.id),
    );
    setSelectedForCancel((prev) => new Set([...prev].filter((id) => allowed.has(id))));
  }, [tasks]);

  const displayError = localError || error;

  // Open the confirm modal (pre-fetch email status)
  const openConfirmModal = useCallback(async () => {
    if (!prompt.trim()) return;
    setConfirmError(null);
    setShowConfirm(true);
    try {
      const status = await getIndexEmailStatus();
      setHasStoredEmail(status.has_email);
      setConfirmEmail(status.email || "");
    } catch {
      setHasStoredEmail(false);
      setConfirmEmail("");
    }
  }, [prompt]);

  const handleConfirmSubmit = useCallback(async () => {
    if (!prompt.trim() || confirmSubmitting) return;
    setConfirmError(null);
    setConfirmSubmitting(true);
    try {
      await submit(prompt.trim(), {
        max_sources: maxSources,
        notify_email: confirmEmail.trim() || undefined,
      });
      setPrompt("");
      setShowConfirm(false);
      setLocalError(null);
    } catch (e: any) {
      setConfirmError(e.message || "Submission failed");
    } finally {
      setConfirmSubmitting(false);
    }
  }, [prompt, maxSources, confirmEmail, confirmSubmitting, submit]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      openConfirmModal();
    }
  }, [openConfirmModal]);

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

  const toggleSelectCancel = useCallback((id: string) => {
    if (!canUserCancelTask(tasks.find((x) => x.id === id)?.status ?? "")) return;
    setSelectedForCancel((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, [tasks]);

  const handleCancelSelected = useCallback(async () => {
    const ids = [...selectedForCancel];
    if (ids.length === 0 || cancellingBulk) return;
    setCancellingBulk(true);
    setLocalError(null);
    try {
      await cancelSelected(ids);
      setSelectedForCancel(new Set());
    } finally {
      setCancellingBulk(false);
    }
  }, [selectedForCancel, cancellingBulk, cancelSelected]);

  const cancellableCount = tasks.filter((t) => canUserCancelTask(t.status)).length;
  const allCancellableSelected =
    cancellableCount > 0 &&
    tasks.filter((t) => canUserCancelTask(t.status)).every((t) => selectedForCancel.has(t.id));

  const toggleSelectAllCancellable = useCallback(() => {
    const cancellable = tasks.filter((t) => canUserCancelTask(t.status));
    if (allCancellableSelected) {
      setSelectedForCancel(new Set());
    } else {
      setSelectedForCancel(new Set(cancellable.map((t) => t.id)));
    }
  }, [tasks, allCancellableSelected]);

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
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Compile a report on the latest advancements in graph RAG..."
              rows={2}
              disabled={submitting}
            />
            <button
              className="btn btn-primary"
              onClick={openConfirmModal}
              disabled={submitting || !prompt.trim()}
            >
              Research
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

        {displayError && <div className="library-error">{displayError}</div>}

        <div className="library-task-list">
          {tasks.length > 0 && (
            <div className="library-bulk-row">
              {cancellableCount > 0 && (
                <label className="library-select-all">
                  <input
                    type="checkbox"
                    checked={allCancellableSelected}
                    onChange={toggleSelectAllCancellable}
                    aria-label="Select all tasks that can be cancelled"
                  />
                  <span>Select all</span>
                </label>
              )}
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={selectedForCancel.size === 0 || cancellingBulk}
                onClick={handleCancelSelected}
              >
                {cancellingBulk
                  ? "Cancelling…"
                  : `Cancel selected${selectedForCancel.size > 0 ? ` (${selectedForCancel.size})` : ""}`}
              </button>
            </div>
          )}
          {loading && tasks.length === 0 && (
            <p className="library-empty">Loading tasks...</p>
          )}
          {!loading && tasks.length === 0 && (
            <p className="library-empty">No research tasks yet. Submit a prompt above to get started.</p>
          )}
          {tasks.map((t) => (
            <div key={t.id} className="library-task-card" onClick={() => openDetail(t.id)}>
              <label
                className="library-task-checkbox-wrap"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  disabled={!canUserCancelTask(t.status)}
                  checked={canUserCancelTask(t.status) && selectedForCancel.has(t.id)}
                  onChange={() => toggleSelectCancel(t.id)}
                  aria-label={
                    canUserCancelTask(t.status)
                      ? "Select for cancel"
                      : "Cannot cancel this task"
                  }
                />
              </label>
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

        {/* ── Confirm modal ── */}
        {showConfirm && (
          <div className="modal-backdrop" onClick={() => !confirmSubmitting && setShowConfirm(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3 style={{ margin: 0 }}>Start Research</h3>
                <button
                  className="btn btn-sm"
                  onClick={() => setShowConfirm(false)}
                  disabled={confirmSubmitting}
                >
                  Close
                </button>
              </div>

              <div style={{ padding: "0.5rem 0 1rem 0", fontSize: "0.85rem", lineHeight: 1.5 }}>
                <p style={{ marginTop: 0 }}>
                  The worker will search the web, scrape up to <strong>{maxSources}</strong> sources,
                  and synthesize a report on:
                </p>
                <blockquote style={{
                  margin: "0.75rem 0",
                  padding: "0.5rem 0.75rem",
                  borderLeft: "3px solid var(--primary)",
                  color: "var(--text)",
                  fontSize: "0.85rem",
                  background: "var(--bg)",
                  borderRadius: "0 6px 6px 0",
                }}>
                  {prompt}
                </blockquote>

                <p className="muted" style={{ fontSize: "0.78rem" }}>
                  This may take several minutes. You can leave this page — we'll email you when it's ready for review.
                </p>

                <div style={{ marginTop: "1rem" }}>
                  <label className="settings-label" htmlFor="library-notify-email">
                    Notification email {hasStoredEmail ? "(on file)" : "(optional)"}
                  </label>
                  <input
                    id="library-notify-email"
                    type="email"
                    value={confirmEmail}
                    onChange={(e) => setConfirmEmail(e.target.value)}
                    placeholder="you@example.com"
                    style={{
                      width: "100%",
                      padding: "8px 10px",
                      background: "var(--bg)",
                      color: "var(--text)",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      fontSize: "0.85rem",
                      boxSizing: "border-box",
                    }}
                  />
                  <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
                    {hasStoredEmail
                      ? "We already have your email. Edit to override."
                      : "Leave blank to skip the notification."}
                  </div>
                </div>

                {confirmError && (
                  <div style={{ marginTop: "0.75rem", color: "var(--danger)", fontSize: "0.8rem" }}>
                    {confirmError}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
                <button
                  className="btn btn-sm"
                  onClick={() => setShowConfirm(false)}
                  disabled={confirmSubmitting}
                >
                  Cancel
                </button>
                <button
                  className="btn btn-sm btn-primary"
                  onClick={handleConfirmSubmit}
                  disabled={confirmSubmitting}
                >
                  {confirmSubmitting ? "Submitting..." : "Start Research"}
                </button>
              </div>
            </div>
          </div>
        )}
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
