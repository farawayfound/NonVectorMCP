import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDocuments } from "../hooks/useDocuments";
import { useChat } from "../hooks/useChat";
import { UploadZone } from "../components/UploadZone";
import { ChatMessage } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatProgress } from "../components/ChatProgress";
import { ChunkingConfig } from "../components/ChunkingConfig";
import { IndexMetrics } from "../components/IndexMetrics";
import { DocumentInsights } from "../components/DocumentInsights";
import { ChunkExplorer, type ExplorerFilter } from "../components/ChunkExplorer";
import { getIndexEmailStatus } from "../api/client";

type Tab = "chat" | "insights" | "explore" | "settings";

export function Workspace() {
  const {
    documents, loading, indexStatus,
    chunkingConfig, metrics, metricsLoading,
    agentConfig, preserveData,
    refresh, upload, remove, deleteAll,
    startIndex, refreshIndex,
    refreshConfig, saveConfig, refreshMetrics,
    refreshAgentConfig, saveAgentConfig,
    refreshPreserve, savePreserve,
  } = useDocuments();
  const { messages, streaming, phase, send, clear } = useChat("/chat/documents");
  const bottomRef = useRef<HTMLDivElement>(null);

  const [tab, setTab] = useState<Tab>("chat");
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);
  const [explorerFilter, setExplorerFilter] = useState<ExplorerFilter>({});

  // Agent config drafts
  const [promptDraft, setPromptDraft] = useState("");
  const [agentSaving, setAgentSaving] = useState<string | null>(null);
  const [agentSuccess, setAgentSuccess] = useState<string | null>(null);

  // Preserve data
  const [preserveChecked, setPreserveChecked] = useState(true);

  // Build-index confirm modal
  const [showBuildModal, setShowBuildModal] = useState(false);
  const [buildInsights, setBuildInsights] = useState(true);
  const [buildEmail, setBuildEmail] = useState("");
  const [hasStoredEmail, setHasStoredEmail] = useState(false);
  const [buildSubmitting, setBuildSubmitting] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);

  useEffect(() => {
    refresh();
    refreshIndex();
    refreshConfig();
    refreshMetrics();
    refreshAgentConfig();
    refreshPreserve();
  }, [refresh, refreshIndex, refreshConfig, refreshMetrics, refreshAgentConfig, refreshPreserve]);

  useEffect(() => {
    if (preserveData) {
      setPreserveChecked(preserveData.preserve);
    }
  }, [preserveData]);

  useEffect(() => {
    if (agentConfig) {
      setPromptDraft(agentConfig.system_prompt ?? "");
    }
  }, [agentConfig]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Auto-select first doc for insights tab
  useEffect(() => {
    if (!selectedDoc && documents.length > 0) {
      setSelectedDoc(documents[0].filename);
    }
    if (selectedDoc && !documents.some((d) => d.filename === selectedDoc)) {
      setSelectedDoc(documents[0]?.filename ?? null);
    }
  }, [documents, selectedDoc]);

  const jobStatus = indexStatus?.job?.status || "idle";
  const indexing = jobStatus === "running" || jobStatus === "building_insights";

  const totalSizeBytes = useMemo(
    () => documents.reduce((sum, d) => sum + (d.size_bytes || 0), 0),
    [documents],
  );
  const totalSizeMB = totalSizeBytes / (1024 * 1024);
  const baseEstimateMin = Math.max(1, Math.round(totalSizeMB * 5));
  const insightsEstimateMin = Math.max(
    baseEstimateMin + 1,
    Math.round(baseEstimateMin * 1.6),
  );

  const openBuildModal = useCallback(async () => {
    setBuildError(null);
    setShowBuildModal(true);
    try {
      const status = await getIndexEmailStatus();
      setHasStoredEmail(status.has_email);
      setBuildEmail(status.email || "");
    } catch {
      setHasStoredEmail(false);
      setBuildEmail("");
    }
  }, []);

  const handleConfirmBuild = useCallback(async () => {
    setBuildError(null);
    setBuildSubmitting(true);
    try {
      const trimmed = buildEmail.trim();
      await startIndex({
        generate_insights: buildInsights,
        notify_email: trimmed || undefined,
      });
      refreshMetrics();
      setShowBuildModal(false);
    } catch (err) {
      setBuildError(err instanceof Error ? err.message : "Failed to start build");
    } finally {
      setBuildSubmitting(false);
    }
  }, [buildInsights, buildEmail, startIndex, refreshMetrics]);

  const agentFlash = (msg: string) => {
    setAgentSuccess(msg);
    setTimeout(() => setAgentSuccess(null), 3000);
  };

  const handleSavePrompt = useCallback(async () => {
    setAgentSaving("prompt");
    try {
      await saveAgentConfig({ system_prompt: promptDraft });
      agentFlash("System prompt saved.");
    } catch {
      // no-op
    } finally {
      setAgentSaving(null);
    }
  }, [saveAgentConfig, promptDraft]);

  const handleSelectDoc = useCallback((filename: string) => {
    setSelectedDoc(filename);
    if (tab === "explore") {
      setExplorerFilter((f) => ({ ...f, doc_id: filename }));
    } else if (tab !== "insights") {
      setTab("insights");
    }
  }, [tab]);

  const handleFilterChunksFromInsights = useCallback(
    (next: { category?: string; entity?: string; tag?: string }) => {
      setExplorerFilter((prev) => ({
        doc_id: selectedDoc ?? prev.doc_id,
        ...next,
      }));
      setTab("explore");
    },
    [selectedDoc],
  );

  const handleAskAboutChunk = useCallback(
    (chunk: { text: string; doc_id: string; page_start?: number | null }) => {
      setTab("chat");
      const snippet = chunk.text.slice(0, 500);
      const preface = `About this excerpt from ${chunk.doc_id}` +
        (chunk.page_start ? ` (page ${chunk.page_start})` : "") +
        `:\n\n"${snippet}"\n\nQuestion: `;
      send(preface);
    },
    [send],
  );

  const tabs: { id: Tab; label: string }[] = useMemo(
    () => [
      { id: "chat", label: "Chat" },
      { id: "insights", label: "Insights" },
      { id: "explore", label: "Explore" },
      { id: "settings", label: "Settings" },
    ],
    [],
  );

  const textareaStyle: React.CSSProperties = {
    width: "100%",
    minHeight: 180,
    padding: "10px 12px",
    background: "var(--bg)",
    color: "var(--text)",
    border: "1px solid var(--border)",
    borderRadius: "6px",
    fontFamily: "monospace",
    fontSize: "0.82rem",
    resize: "vertical",
    boxSizing: "border-box",
  };

  const defaultPrompt = agentConfig?.default_system_prompt || "";
  const adminSystemRules = agentConfig?.default_system_rules || "";
  const savedPrompt = agentConfig?.system_prompt ?? "";

  return (
    <div className="workspace-page">
      <div className="workspace-sidebar">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Workspace</h2>
          {documents.length > 0 && (
            <button
              className="btn btn-sm btn-danger"
              style={{ fontSize: "0.75rem", padding: "3px 10px" }}
              onClick={async () => {
                if (!confirm("Delete ALL your documents and indexes? This cannot be undone.")) return;
                await deleteAll();
                refresh();
                refreshIndex();
                refreshMetrics();
              }}
            >
              Delete All
            </button>
          )}
        </div>
        <UploadZone onUpload={upload} />

        <div className="document-list">
          {loading && <p>Loading...</p>}
          {!loading && documents.length === 0 && <p className="muted">No documents uploaded yet.</p>}
          {documents.map((doc) => (
            <div
              key={doc.filename}
              className={`document-card ${selectedDoc === doc.filename ? "is-selected" : ""}`}
            >
              <button
                className="doc-select-btn"
                onClick={() => handleSelectDoc(doc.filename)}
                title="Open insights"
              >
                <span className="doc-name">{doc.filename}</span>
                <span className="doc-meta">
                  {(doc.size_bytes < 1024 * 1024
                    ? `${(doc.size_bytes / 1024).toFixed(1)} KB`
                    : `${(doc.size_bytes / (1024 * 1024)).toFixed(1)} MB`)}
                  {" · "}
                  {doc.suffix}
                </span>
              </button>
              <button
                className="btn btn-sm btn-danger"
                onClick={(e) => {
                  e.stopPropagation();
                  remove(doc.filename);
                }}
              >
                Delete
              </button>
            </div>
          ))}
        </div>

        <div className="settings-preserve" style={{ marginTop: "0.75rem" }}>
          <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", fontSize: "0.82rem" }}>
            <input
              type="checkbox"
              checked={preserveChecked}
              onChange={(e) => {
                const checked = e.target.checked;
                setPreserveChecked(checked);
                void savePreserve(checked);
                agentFlash(checked ? "Data will be preserved." : "Data will be cleared on logout.");
              }}
              style={{ marginTop: "2px" }}
            />
            <span>Preserve data for next session</span>
          </label>
          <div style={{ marginTop: "0.35rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
            {preserveChecked
              ? "Your documents and index will be kept until your next login."
              : "Data is cleared on logout or after 24 hours of inactivity."}
          </div>
        </div>

        <IndexMetrics metrics={metrics} loading={metricsLoading} />

        <div className="index-controls">
          <button
            className="btn btn-primary btn-block"
            onClick={openBuildModal}
            disabled={indexing || documents.length === 0}
          >
            {jobStatus === "running" && "Indexing..."}
            {jobStatus === "building_insights" && "Building insights..."}
            {!indexing && "Build Index"}
          </button>
          {indexStatus?.last_run && (
            <p className="muted">
              Last indexed: {indexStatus.last_run.chunks} chunks from {indexStatus.last_run.files} files
            </p>
          )}
        </div>
      </div>

      <div className="workspace-main">
        <div className="workspace-tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={`workspace-tab ${tab === t.id ? "is-active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="workspace-tab-body">
          {tab === "chat" && (
            <>
              <div className="chat-messages">
                {messages.length === 0 && (
                  <div className="chat-empty">
                    <p>Upload and index documents, then ask questions about them.</p>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <ChatMessage key={i} message={msg} />
                ))}
                {streaming && <ChatProgress phase={phase} />}
                <div ref={bottomRef} />
              </div>
              <div className="chat-footer">
                {messages.length > 0 && (
                  <button onClick={clear} className="btn btn-sm" style={{ marginBottom: 8 }}>
                    Clear
                  </button>
                )}
                <ChatInput
                  onSend={send}
                  disabled={streaming}
                  placeholder="Ask about your documents..."
                />
              </div>
            </>
          )}

          {tab === "insights" && (
            <DocumentInsights docId={selectedDoc} onFilterChunks={handleFilterChunksFromInsights} />
          )}

          {tab === "explore" && (
            <ChunkExplorer
              filter={explorerFilter}
              onChangeFilter={setExplorerFilter}
              onAskAboutChunk={handleAskAboutChunk}
            />
          )}

          {tab === "settings" && (
            <div className="settings-panel">
              <ChunkingConfig
                config={chunkingConfig}
                onSave={saveConfig}
                disabled={indexing}
                alwaysExpanded
              />

              <h3>Agent Settings</h3>
              <p className="muted" style={{ fontSize: "0.78rem", marginTop: "-0.3rem" }}>
                Override the default system prompt below. System rules are set by an administrator only.
              </p>

              {agentSuccess && (
                <div className="flash-success">{agentSuccess}</div>
              )}

              <div style={{ marginBottom: "1.25rem" }}>
                <label className="settings-label">System rules</label>
                <p className="muted" style={{ fontSize: "0.78rem", margin: "0 0 0.5rem" }}>
                  These are defined in the admin configuration. They apply to every user and cannot be edited here.
                </p>
                {adminSystemRules ? (
                  <textarea
                    style={{
                      ...textareaStyle,
                      minHeight: 120,
                      opacity: 0.92,
                      cursor: "default",
                    }}
                    value={adminSystemRules}
                    readOnly
                    spellCheck={false}
                    aria-readonly="true"
                  />
                ) : (
                  <p className="muted" style={{ fontSize: "0.82rem", margin: 0 }}>
                    No additional system rules are configured.
                  </p>
                )}
              </div>

              <div style={{ marginBottom: "1.25rem" }}>
                <label className="settings-label">System Prompt</label>
                <textarea
                  style={textareaStyle}
                  value={promptDraft}
                  onChange={(e) => setPromptDraft(e.target.value)}
                  placeholder={defaultPrompt || "Built-in default prompt is active…"}
                  spellCheck={false}
                />
                <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={handleSavePrompt}
                    disabled={agentSaving === "prompt" || promptDraft === savedPrompt}
                  >
                    {agentSaving === "prompt" ? "Saving…" : "Save"}
                  </button>
                  {savedPrompt && (
                    <button
                      className="btn btn-sm"
                      onClick={async () => {
                        setAgentSaving("prompt");
                        try {
                          await saveAgentConfig({ system_prompt: "" });
                          setPromptDraft("");
                          agentFlash("Reset to default.");
                        } catch { /* no-op */ } finally {
                          setAgentSaving(null);
                        }
                      }}
                    >
                      Reset
                    </button>
                  )}
                </div>
              </div>

            </div>
          )}
        </div>
      </div>

      {showBuildModal && (
        <div className="modal-backdrop" onClick={() => !buildSubmitting && setShowBuildModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>Build Index</h3>
              <button
                className="btn btn-sm"
                onClick={() => setShowBuildModal(false)}
                disabled={buildSubmitting}
              >
                Close
              </button>
            </div>
            <div style={{ padding: "0.5rem 0 1rem 0", fontSize: "0.85rem", lineHeight: 1.5 }}>
              <p style={{ marginTop: 0 }}>
                Indexing {documents.length} document{documents.length === 1 ? "" : "s"}
                {" "}({totalSizeMB.toFixed(1)} MB total).
              </p>
              <p className="muted" style={{ fontSize: "0.78rem" }}>
                Estimate: <strong>~{baseEstimateMin} min</strong> without insights,
                {" "}<strong>~{insightsEstimateMin} min</strong> with insights.
                Roughly 5 minutes per MB, more with insights enabled.
              </p>
              <p className="muted" style={{ fontSize: "0.78rem" }}>
                You can step away — we'll email you when ChunkyPotato has finished baking your index.
              </p>

              <label style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", marginTop: "1rem" }}>
                <input
                  type="checkbox"
                  checked={buildInsights}
                  onChange={(e) => setBuildInsights(e.target.checked)}
                  style={{ marginTop: "2px" }}
                />
                <span>
                  <strong>Generate insights</strong>
                  <div className="muted" style={{ fontSize: "0.75rem" }}>
                    Summaries, entities, PII findings per document. Adds time but powers the Insights tab.
                  </div>
                </span>
              </label>

              <div style={{ marginTop: "1rem" }}>
                <label className="settings-label" htmlFor="notify-email">
                  Notification email {hasStoredEmail ? "(on file)" : "(optional)"}
                </label>
                <input
                  id="notify-email"
                  type="email"
                  value={buildEmail}
                  onChange={(e) => setBuildEmail(e.target.value)}
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

              {buildError && (
                <div style={{ marginTop: "0.75rem", color: "var(--danger, #ef4444)", fontSize: "0.8rem" }}>
                  {buildError}
                </div>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
              <button
                className="btn btn-sm"
                onClick={() => setShowBuildModal(false)}
                disabled={buildSubmitting}
              >
                Cancel
              </button>
              <button
                className="btn btn-sm btn-primary"
                onClick={handleConfirmBuild}
                disabled={buildSubmitting}
              >
                {buildSubmitting ? "Starting…" : "Start Build"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
