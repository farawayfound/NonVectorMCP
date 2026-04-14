import { useCallback, useEffect, useMemo, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLibrary, type LibraryTask } from "../hooks/useLibrary";
import { getLibraryTask, getIndexEmailStatus } from "../api/client";

type View = "list" | "detail";

const MAX_LIBRARY_SOURCES = 20;
const MAX_CONCURRENT_ACTIVE_TASKS = 2;
const MIN_TARGET_TOKENS = 300;
const MAX_TARGET_TOKENS = 8000;

const OUTPUT_FORMAT_OPTIONS: { value: string; label: string; description: string }[] = [
  { value: "default", label: "Default", description: "Mixed report: intro, sections with bullets, comparison table(s), takeaways." },
  { value: "essay", label: "Essay", description: "Flowing prose essay — intro, body, conclusion. No bullets or tables." },
  { value: "graphical", label: "Graphical", description: "Mostly tables and ASCII charts with a short intro and conclusion." },
  { value: "contrast", label: "Contrast", description: "Focus on differences and disagreements between sources." },
  { value: "correlate", label: "Correlate", description: "Focus on shared findings and converging evidence across sources." },
];

function defaultTargetTokens(maxSources: number): number {
  return 300 + maxSources * 100;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  crawling: "Crawling",
  synthesizing: "Synthesizing",
  review: "Completed",
  approved: "Imported",
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

function canCancel(status: string) {
  return ["queued", "crawling", "synthesizing"].includes(status);
}

function canImport(status: string) {
  return status === "review";
}

function LibraryReportMarkdown({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ href, children, ...rest }: ComponentPropsWithoutRef<"a">) => (
          <a href={href} {...rest} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}

export function Library() {
  const {
    tasks, loading, submitting, error,
    refresh, submit, importOne, importSelected, deleteSelected, cancelSelected,
  } = useLibrary();

  const [view, setView] = useState<View>("list");
  const [prompt, setPrompt] = useState("");
  const [maxSources, setMaxSources] = useState(5);
  const [targetTokens, setTargetTokens] = useState<number>(() => defaultTargetTokens(5));
  const [targetTokensTouched, setTargetTokensTouched] = useState(false);
  const [outputFormat, setOutputFormat] = useState<string>("default");
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

  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkAction, setBulkAction] = useState<null | "cancel" | "import" | "delete">(null);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    setMaxSources((n) => Math.min(MAX_LIBRARY_SOURCES, Math.max(1, n)));
  }, []);

  // Keep target tokens in sync with the max-sources-based default until the
  // user manually overrides it, at which point we stop recomputing.
  useEffect(() => {
    if (!targetTokensTouched) {
      setTargetTokens(defaultTargetTokens(maxSources));
    }
  }, [maxSources, targetTokensTouched]);

  const activePipelineCount = useMemo(
    () => tasks.filter((t) => isActive(t.status)).length,
    [tasks],
  );
  const atConcurrentLimit = activePipelineCount >= MAX_CONCURRENT_ACTIVE_TASKS;

  useEffect(() => {
    const existing = new Set(tasks.map((t) => t.id));
    setSelectedIds((prev) => new Set([...prev].filter((id) => existing.has(id))));
  }, [tasks]);

  const selectedTasks = useMemo(
    () => tasks.filter((t) => selectedIds.has(t.id)),
    [tasks, selectedIds],
  );
  const canBulkCancel =
    selectedTasks.length > 0 && selectedTasks.every((t) => canCancel(t.status));
  const canBulkImport =
    selectedTasks.length > 0 && selectedTasks.every((t) => canImport(t.status));
  const canBulkDelete = selectedTasks.length > 0;

  const displayError = localError || error;

  // Open the confirm modal (pre-fetch email status)
  const openConfirmModal = useCallback(async () => {
    if (!prompt.trim() || atConcurrentLimit) return;
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
  }, [prompt, atConcurrentLimit]);

  const handleConfirmSubmit = useCallback(async () => {
    if (!prompt.trim() || confirmSubmitting) return;
    setConfirmError(null);
    setConfirmSubmitting(true);
    try {
      await submit(prompt.trim(), {
        max_sources: maxSources,
        target_tokens: targetTokens,
        output_format: outputFormat,
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

  const handleImportOne = useCallback(async () => {
    if (!selectedId) return;
    try {
      const res = await importOne(selectedId);
      setApproveResult(res);
      const t = await getLibraryTask(selectedId);
      setDetail(t);
    } catch {
      // shown via hook error
    }
  }, [selectedId, importOne]);

  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleImportSelected = useCallback(async () => {
    const ids = [...selectedIds];
    if (ids.length === 0 || bulkAction) return;
    setBulkAction("import");
    setLocalError(null);
    try {
      await importSelected(ids);
      setSelectedIds(new Set());
    } finally {
      setBulkAction(null);
    }
  }, [selectedIds, bulkAction, importSelected]);

  const handleCancelSelected = useCallback(async () => {
    const ids = [...selectedIds];
    if (ids.length === 0 || bulkAction) return;
    setBulkAction("cancel");
    setLocalError(null);
    try {
      await cancelSelected(ids);
      setSelectedIds(new Set());
    } finally {
      setBulkAction(null);
    }
  }, [selectedIds, bulkAction, cancelSelected]);

  const handleDeleteSelected = useCallback(async () => {
    const ids = [...selectedIds];
    if (ids.length === 0 || bulkAction) return;
    if (!window.confirm(`Delete ${ids.length} task${ids.length === 1 ? "" : "s"} and their researched documents? This cannot be undone.`)) return;
    setBulkAction("delete");
    setLocalError(null);
    try {
      await deleteSelected(ids);
      setSelectedIds(new Set());
    } finally {
      setBulkAction(null);
    }
  }, [selectedIds, bulkAction, deleteSelected]);

  const allSelected = tasks.length > 0 && tasks.every((t) => selectedIds.has(t.id));

  const toggleSelectAll = useCallback(() => {
    if (allSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(tasks.map((t) => t.id)));
  }, [tasks, allSelected]);

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
          {atConcurrentLimit && (
            <p className="library-concurrent-notice" role="status">
              You already have {MAX_CONCURRENT_ACTIVE_TASKS} tasks queued or running. Cancel one or wait until
              a task reaches review before submitting another.
            </p>
          )}
          <div className="library-input-row">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value.slice(0, 380))}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Compile a report on the latest advancements in graph RAG..."
              rows={2}
              maxLength={380}
              disabled={submitting}
            />
            <button
              className="btn btn-primary"
              onClick={openConfirmModal}
              disabled={submitting || !prompt.trim() || atConcurrentLimit}
              title={atConcurrentLimit ? "Wait for a task to finish or cancel one" : undefined}
            >
              Research
            </button>
          </div>
          <div style={{ textAlign: "right", fontSize: "0.75rem", color: prompt.length >= 360 ? "var(--danger, #ef4444)" : "var(--text-muted)", marginTop: "0.25rem" }}>
            {prompt.length}/380
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
                  Max sources (1–{MAX_LIBRARY_SOURCES}):
                  <input
                    type="number"
                    min={1}
                    max={MAX_LIBRARY_SOURCES}
                    value={maxSources}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isNaN(v)) return;
                      setMaxSources(Math.min(MAX_LIBRARY_SOURCES, Math.max(1, v)));
                    }}
                  />
                </label>
                <label>
                  Target report size ({MIN_TARGET_TOKENS}–{MAX_TARGET_TOKENS} tokens):
                  <input
                    type="number"
                    min={MIN_TARGET_TOKENS}
                    max={MAX_TARGET_TOKENS}
                    step={50}
                    value={targetTokens}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (Number.isNaN(v)) return;
                      setTargetTokensTouched(true);
                      setTargetTokens(
                        Math.min(MAX_TARGET_TOKENS, Math.max(MIN_TARGET_TOKENS, Math.round(v))),
                      );
                    }}
                  />
                  {targetTokensTouched && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      style={{ marginLeft: "0.4rem" }}
                      onClick={() => {
                        setTargetTokensTouched(false);
                        setTargetTokens(defaultTargetTokens(maxSources));
                      }}
                      title="Reset to default (600 + Max Sources × 180)"
                    >
                      Reset
                    </button>
                  )}
                </label>
                <label>
                  Output format:
                  <select
                    value={outputFormat}
                    onChange={(e) => setOutputFormat(e.target.value)}
                  >
                    {OUTPUT_FORMAT_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                  <span
                    className="muted"
                    style={{ display: "block", fontSize: "0.72rem", marginTop: "0.25rem" }}
                  >
                    {OUTPUT_FORMAT_OPTIONS.find((o) => o.value === outputFormat)?.description}
                  </span>
                </label>
              </div>
            )}
          </div>
        </div>

        {displayError && <div className="library-error">{displayError}</div>}

        <div className="library-task-list">
          {tasks.length > 0 && (
            <div className="library-bulk-row">
              <label className="library-select-all">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  aria-label="Select all tasks"
                />
                <span>Select all</span>
              </label>
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={!canBulkImport || bulkAction !== null}
                onClick={handleImportSelected}
                title={
                  selectedIds.size === 0
                    ? "Select one or more Completed tasks"
                    : canBulkImport
                      ? "Import selected tasks into Workspace"
                      : "Only Completed tasks can be imported"
                }
              >
                {bulkAction === "import"
                  ? "Importing…"
                  : `Import to Workspace${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={!canBulkCancel || bulkAction !== null}
                onClick={handleCancelSelected}
                title={
                  selectedIds.size === 0
                    ? "Select one or more Queued/Running tasks"
                    : canBulkCancel
                      ? "Cancel selected tasks"
                      : "Only Queued or Running tasks can be cancelled"
                }
              >
                {bulkAction === "cancel"
                  ? "Cancelling…"
                  : `Cancel Selected${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
              </button>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                disabled={!canBulkDelete || bulkAction !== null}
                onClick={handleDeleteSelected}
                title="Delete selected tasks and their research documents"
              >
                {bulkAction === "delete"
                  ? "Deleting…"
                  : `Delete${selectedIds.size > 0 ? ` (${selectedIds.size})` : ""}`}
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
                  checked={selectedIds.has(t.id)}
                  onChange={() => toggleSelect(t.id)}
                  aria-label="Select task"
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
                  and synthesize a <strong>{OUTPUT_FORMAT_OPTIONS.find((o) => o.value === outputFormat)?.label || "Default"}</strong>-format
                  report targeting ~<strong>{targetTokens}</strong> tokens on:
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
                  disabled={confirmSubmitting || atConcurrentLimit}
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
              <div className="library-artifact-content library-artifact-markdown">
                <LibraryReportMarkdown markdown={detail.artifact} />
              </div>
            </div>
          )}

          {detail.error && (
            <div className="library-error">Error: {detail.error}</div>
          )}

          {approveResult && (
            <div className={`library-approve-result ${approveResult.status === "approved" ? "success" : ""}`}>
              {approveResult.status === "approved" && (
                <span>Imported as <strong>{approveResult.filename}</strong>. Build your index from Workspace to include it in RAG.</span>
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
              <button className="btn btn-primary" onClick={handleImportOne}>
                Import to Workspace
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
