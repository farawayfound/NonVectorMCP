import { useEffect, useState } from "react";
import { getDocumentInsights } from "../api/client";

interface Props {
  docId: string | null;
  onFilterChunks: (filter: { category?: string; entity?: string; tag?: string }) => void;
}

interface Insights {
  doc_id: string;
  summary?: string;
  chunk_count?: number;
  word_count?: number;
  page_count?: number | null;
  reading_time_min?: number;
  categories?: Record<string, number>;
  top_entities?: { label: string; kind: string; count: number }[];
  top_key_phrases?: { phrase: string; count: number }[];
  top_tags?: { tag: string; count: number }[];
  pii_counts?: Record<string, number>;
  empty?: boolean;
  error?: string;
}

const PII_LABELS: Record<string, string> = {
  EMAIL: "Emails",
  PHONE: "Phones",
  CREDENTIAL: "Credentials",
  ACCOUNT_NUMBER: "Account numbers",
  ADDRESS: "Addresses",
  PERSON_NAME: "Person names",
};

export function DocumentInsights({ docId, onFilterChunks }: Props) {
  const [data, setData] = useState<Insights | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!docId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDocumentInsights(docId)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "Failed to load insights");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId]);

  if (!docId) {
    return (
      <div className="workspace-empty">
        <p className="muted">Select a document from the sidebar to see its insights.</p>
      </div>
    );
  }
  if (loading) return <div className="workspace-empty"><p className="muted">Loading insights…</p></div>;
  if (error) return <div className="workspace-empty"><p className="muted">{error}</p></div>;
  if (!data) return null;
  if (data.empty) {
    return (
      <div className="workspace-empty">
        <p className="muted">No indexed chunks for this document yet. Build the index first.</p>
      </div>
    );
  }

  const categoryEntries = Object.entries(data.categories || {});
  const totalChunks = data.chunk_count || 0;

  return (
    <div className="insights-panel">
      <header className="insights-header">
        <h3 style={{ margin: 0 }}>{data.doc_id}</h3>
        <div className="insights-stats">
          <span>{data.chunk_count ?? 0} chunks</span>
          {data.page_count ? <span>{data.page_count} pages</span> : null}
          <span>{data.word_count ?? 0} words</span>
          {data.reading_time_min ? <span>~{data.reading_time_min} min read</span> : null}
        </div>
      </header>

      {data.summary && (
        <section className="insights-section">
          <h4>Summary</h4>
          <p className="insights-summary">{data.summary}</p>
        </section>
      )}

      {categoryEntries.length > 0 && (
        <section className="insights-section">
          <h4>Category mix</h4>
          <div className="insights-bar">
            {categoryEntries.map(([cat, n]) => {
              const pct = totalChunks ? Math.round((n / totalChunks) * 100) : 0;
              return (
                <button
                  key={cat}
                  className="insights-bar-seg"
                  style={{ flex: `${n} 0 0%` }}
                  title={`${cat}: ${n} chunks (${pct}%)`}
                  onClick={() => onFilterChunks({ category: cat })}
                >
                  <span>{cat}</span>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {data.top_entities && data.top_entities.length > 0 && (
        <section className="insights-section">
          <h4>Top entities</h4>
          <div className="chip-row">
            {data.top_entities.map((e) => (
              <button
                key={`${e.label}-${e.kind}`}
                className="chip"
                onClick={() => onFilterChunks({ entity: e.label })}
                title={e.kind ? `${e.kind} · ${e.count} mentions` : `${e.count} mentions`}
              >
                {e.label} <span className="chip-count">{e.count}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {data.top_key_phrases && data.top_key_phrases.length > 0 && (
        <section className="insights-section">
          <h4>Key phrases</h4>
          <div className="chip-row">
            {data.top_key_phrases.slice(0, 18).map((p) => (
              <span key={p.phrase} className="chip chip-muted">
                {p.phrase} <span className="chip-count">{p.count}</span>
              </span>
            ))}
          </div>
        </section>
      )}

      {data.top_tags && data.top_tags.length > 0 && (
        <section className="insights-section">
          <h4>Tags</h4>
          <div className="chip-row">
            {data.top_tags.map((t) => (
              <button
                key={t.tag}
                className="chip"
                onClick={() => onFilterChunks({ tag: t.tag })}
              >
                {t.tag} <span className="chip-count">{t.count}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {data.pii_counts && Object.keys(data.pii_counts).length > 0 && (
        <section className="insights-section">
          <h4>PII redactions</h4>
          <div className="chip-row">
            {Object.entries(data.pii_counts).map(([kind, n]) => (
              <span key={kind} className="chip chip-warn">
                {PII_LABELS[kind] || kind} <span className="chip-count">{n}</span>
              </span>
            ))}
          </div>
          <p className="muted" style={{ fontSize: "0.75rem", marginTop: "0.4rem" }}>
            Values were replaced with neutral markers during indexing.
          </p>
        </section>
      )}
    </div>
  );
}
