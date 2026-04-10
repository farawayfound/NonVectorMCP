import React, { useEffect, useRef, useCallback, useState } from "react";
import { useDocuments } from "../hooks/useDocuments";
import { useChat } from "../hooks/useChat";
import { UploadZone } from "../components/UploadZone";
import { DocumentCard } from "../components/DocumentCard";
import { ChatMessage } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatProgress } from "../components/ChatProgress";
import { ChunkingConfig } from "../components/ChunkingConfig";
import { IndexMetrics } from "../components/IndexMetrics";

export function YourDocuments() {
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

  // Agent config drafts
  const [promptDraft, setPromptDraft] = useState("");
  const [rulesDraft, setRulesDraft] = useState("");
  const [agentSaving, setAgentSaving] = useState<string | null>(null);
  const [agentSuccess, setAgentSuccess] = useState<string | null>(null);

  // Preserve data checkbox (local draft, not saved until Confirm)
  const [preserveChecked, setPreserveChecked] = useState(false);
  const [preserveConfirmed, setPreserveConfirmed] = useState(false);

  useEffect(() => {
    refresh();
    refreshIndex();
    refreshConfig();
    refreshMetrics();
    refreshAgentConfig();
    refreshPreserve();
  }, [refresh, refreshIndex, refreshConfig, refreshMetrics, refreshAgentConfig, refreshPreserve]);

  // Sync preserve checkbox with server state
  useEffect(() => {
    if (preserveData) {
      setPreserveChecked(preserveData.preserve);
      setPreserveConfirmed(preserveData.preserve);
    }
  }, [preserveData]);

  // Sync drafts when agentConfig loads
  useEffect(() => {
    if (agentConfig) {
      setPromptDraft(agentConfig.system_prompt ?? "");
      setRulesDraft(agentConfig.system_rules ?? "");
    }
  }, [agentConfig]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const jobStatus = indexStatus?.job?.status || "idle";

  const handleStartIndex = useCallback(async () => {
    await startIndex();
    refreshMetrics();
  }, [startIndex, refreshMetrics]);

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

  const handleSaveRules = useCallback(async () => {
    setAgentSaving("rules");
    try {
      await saveAgentConfig({ system_rules: rulesDraft });
      agentFlash("Rules saved.");
    } catch {
      // no-op
    } finally {
      setAgentSaving(null);
    }
  }, [saveAgentConfig, rulesDraft]);

  const textareaStyle: React.CSSProperties = {
    width: "100%",
    minHeight: 200,
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
  const defaultRules = agentConfig?.default_system_rules || "";
  const savedPrompt = agentConfig?.system_prompt ?? "";
  const savedRules = agentConfig?.system_rules ?? "";

  return (
    <div className="documents-page">
      <div className="documents-sidebar">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>Your Documents</h2>
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
            <DocumentCard key={doc.filename} doc={doc} onDelete={remove} />
          ))}
        </div>

        <ChunkingConfig
          config={chunkingConfig}
          onSave={saveConfig}
          disabled={jobStatus === "running"}
        />

        <IndexMetrics metrics={metrics} loading={metricsLoading} />

        <div className="index-controls">
          <button
            className="btn btn-primary btn-block"
            onClick={handleStartIndex}
            disabled={jobStatus === "running" || documents.length === 0}
          >
            {jobStatus === "running" ? "Indexing..." : "Build Index"}
          </button>
          {indexStatus?.last_run && (
            <p className="muted">
              Last indexed: {indexStatus.last_run.chunks} chunks from {indexStatus.last_run.files} files
            </p>
          )}
        </div>
      </div>

      <div className="documents-chat">
        <div className="chat-header">
          <h2>Chat with Your Documents</h2>
          {messages.length > 0 && (
            <button onClick={clear} className="btn btn-sm">Clear</button>
          )}
        </div>

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

        <ChatInput
          onSend={send}
          disabled={streaming}
          placeholder="Ask about your documents..."
        />
      </div>

      <div className="documents-config-sidebar">
        <h3 style={{ margin: "0 0 0.25rem" }}>Agent Settings</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.78rem", margin: "0 0 1rem" }}>
          Type in new values to replace the defaults.
        </p>

        {agentSuccess && (
          <div
            style={{
              marginBottom: "0.75rem",
              padding: "6px 10px",
              background: "color-mix(in srgb, var(--success) 12%, var(--bg-card))",
              border: "1px solid color-mix(in srgb, var(--success) 30%, var(--border))",
              borderRadius: "6px",
              color: "var(--success)",
              fontSize: "0.8rem",
            }}
          >
            {agentSuccess}
          </div>
        )}

        <div style={{ marginBottom: "1.25rem" }}>
          <label style={{
            display: "block",
            fontSize: "0.75rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "var(--text-muted)",
            marginBottom: "0.4rem",
          }}>
            System Prompt
          </label>
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
                style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
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
          {!savedPrompt && (
            <div style={{ marginTop: "0.3rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Using admin default prompt.
            </div>
          )}
        </div>

        <div>
          <label style={{
            display: "block",
            fontSize: "0.75rem",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "var(--text-muted)",
            marginBottom: "0.4rem",
          }}>
            Rules
          </label>
          <textarea
            style={textareaStyle}
            value={rulesDraft}
            onChange={(e) => setRulesDraft(e.target.value)}
            placeholder={defaultRules || "No default rules set. Add custom rules here…"}
            spellCheck={false}
          />
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleSaveRules}
              disabled={agentSaving === "rules" || rulesDraft === savedRules}
            >
              {agentSaving === "rules" ? "Saving…" : "Save"}
            </button>
            {savedRules && (
              <button
                className="btn btn-sm"
                style={{ background: "var(--bg)", border: "1px solid var(--border)", color: "var(--text-muted)" }}
                onClick={async () => {
                  setAgentSaving("rules");
                  try {
                    await saveAgentConfig({ system_rules: "" });
                    setRulesDraft("");
                    agentFlash("Rules cleared.");
                  } catch { /* no-op */ } finally {
                    setAgentSaving(null);
                  }
                }}
              >
                Clear
              </button>
            )}
          </div>
          {!savedRules && (
            <div style={{ marginTop: "0.3rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Using admin default rules.
            </div>
          )}
        </div>

        {/* ── Preserve Data ── */}
        <div style={{
          marginTop: "auto",
          paddingTop: "1.25rem",
          borderTop: "1px solid var(--border)",
        }}>
          <label style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "0.5rem",
            cursor: "pointer",
            fontSize: "0.82rem",
          }}>
            <input
              type="checkbox"
              checked={preserveChecked}
              onChange={(e) => {
                setPreserveChecked(e.target.checked);
                // If unchecking, auto-save immediately
                if (!e.target.checked && preserveConfirmed) {
                  savePreserve(false);
                  setPreserveConfirmed(false);
                  agentFlash("Data will be cleared on logout.");
                }
              }}
              style={{ marginTop: "2px" }}
            />
            <span>Preserve data for next session</span>
          </label>
          {preserveChecked && !preserveConfirmed && (
            <div style={{
              marginTop: "0.5rem",
              padding: "8px 10px",
              background: "color-mix(in srgb, #f59e0b 8%, var(--bg-card))",
              border: "1px solid color-mix(in srgb, #f59e0b 25%, var(--border))",
              borderRadius: "6px",
              fontSize: "0.78rem",
              color: "var(--text-muted)",
            }}>
              <p style={{ margin: "0 0 0.5rem" }}>
                Your documents and index will be kept
                {preserveData?.session_expires_at
                  ? ` until ${new Date(preserveData.session_expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`
                  : ""
                } or until your next login.
              </p>
              <p style={{ margin: "0 0 0.5rem" }}>
                If unchecked, all data is automatically wiped on logout or after 20 minutes of inactivity.
              </p>
              <button
                className="btn btn-sm btn-primary"
                onClick={async () => {
                  await savePreserve(true);
                  setPreserveConfirmed(true);
                  agentFlash("Data will be preserved.");
                }}
              >
                Confirm
              </button>
            </div>
          )}
          {preserveConfirmed && (
            <div style={{ marginTop: "0.4rem", fontSize: "0.75rem", color: "var(--success)" }}>
              Data will be preserved
              {preserveData?.session_expires_at
                ? ` until ${new Date(preserveData.session_expires_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}`
                : ""
              }.
            </div>
          )}
          {!preserveChecked && !preserveConfirmed && (
            <div style={{ marginTop: "0.3rem", fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Data is cleared on logout or after 20 min of inactivity.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
