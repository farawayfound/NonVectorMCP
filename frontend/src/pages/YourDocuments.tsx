import { useEffect, useRef } from "react";
import { useDocuments } from "../hooks/useDocuments";
import { useChat } from "../hooks/useChat";
import { UploadZone } from "../components/UploadZone";
import { DocumentCard } from "../components/DocumentCard";
import { ChatMessage } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";

export function YourDocuments() {
  const { documents, loading, indexStatus, refresh, upload, remove, startIndex, refreshIndex } =
    useDocuments();
  const { messages, streaming, send, clear } = useChat("/chat/documents");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    refresh();
    refreshIndex();
  }, [refresh, refreshIndex]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const jobStatus = indexStatus?.job?.status || "idle";

  return (
    <div className="documents-page">
      <div className="documents-sidebar">
        <h2>Your Documents</h2>
        <UploadZone onUpload={upload} />

        <div className="document-list">
          {loading && <p>Loading...</p>}
          {!loading && documents.length === 0 && <p className="muted">No documents uploaded yet.</p>}
          {documents.map((doc) => (
            <DocumentCard key={doc.filename} doc={doc} onDelete={remove} />
          ))}
        </div>

        <div className="index-controls">
          <button
            className="btn btn-primary btn-block"
            onClick={startIndex}
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
          <div ref={bottomRef} />
        </div>

        <ChatInput
          onSend={send}
          disabled={streaming}
          placeholder="Ask about your documents..."
        />
      </div>
    </div>
  );
}
