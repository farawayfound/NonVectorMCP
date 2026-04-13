import { useCallback, useEffect, useMemo, useState } from "react";
import { listChunks, type ChunkQuery } from "../api/client";

interface Chunk {
  id: string;
  doc_id: string;
  category: string;
  tags: string[];
  breadcrumb?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  text: string;
  entities: string[];
  related_chunks: string[];
}

interface Facets {
  categories?: Record<string, number>;
  tags?: Record<string, number>;
  entities?: Record<string, number>;
  documents?: Record<string, number>;
}

export interface ExplorerFilter {
  doc_id?: string;
  category?: string;
  tag?: string;
  entity?: string;
}

interface Props {
  filter: ExplorerFilter;
  onChangeFilter: (f: ExplorerFilter) => void;
  onAskAboutChunk: (chunk: Chunk) => void;
}

function Highlight({ text, needle }: { text: string; needle: string }) {
  if (!needle) return <>{text}</>;
  const parts = text.split(new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "ig"));
  return (
    <>
      {parts.map((p, i) =>
        p.toLowerCase() === needle.toLowerCase() ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>,
      )}
    </>
  );
}

export function ChunkExplorer({ filter, onChangeFilter, onAskAboutChunk }: Props) {
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [facets, setFacets] = useState<Facets>({});
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Chunk | null>(null);

  useEffect(() => {
    const h = setTimeout(() => setDebouncedQ(q.trim()), 250);
    return () => clearTimeout(h);
  }, [q]);

  const query: ChunkQuery = useMemo(
    () => ({ ...filter, q: debouncedQ || undefined, limit: 50 }),
    [filter, debouncedQ],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listChunks(query)
      .then((res) => {
        if (cancelled) return;
        setChunks(res.chunks || []);
        setFacets(res.facets || {});
        setTotal(res.total || 0);
      })
      .catch((err) => !cancelled && setError(err?.message || "Failed to load chunks"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query]);

  const clearKey = useCallback(
    (key: keyof ExplorerFilter) => {
      const next = { ...filter };
      delete next[key];
      onChangeFilter(next);
    },
    [filter, onChangeFilter],
  );

  const setKey = useCallback(
    (key: keyof ExplorerFilter, value: string) => {
      if (filter[key] === value) {
        clearKey(key);
      } else {
        onChangeFilter({ ...filter, [key]: value });
      }
    },
    [filter, onChangeFilter, clearKey],
  );

  const activeFilterChips: { key: keyof ExplorerFilter; label: string; value: string }[] = [];
  if (filter.doc_id) activeFilterChips.push({ key: "doc_id", label: "doc", value: filter.doc_id });
  if (filter.category) activeFilterChips.push({ key: "category", label: "category", value: filter.category });
  if (filter.tag) activeFilterChips.push({ key: "tag", label: "tag", value: filter.tag });
  if (filter.entity) activeFilterChips.push({ key: "entity", label: "entity", value: filter.entity });

  return (
    <div className="explorer">
      <div className="explorer-body">
        <aside className="explorer-facets">
          <FacetGroup
            title="Categories"
            facet={facets.categories}
            selected={filter.category}
            onSelect={(v) => setKey("category", v)}
          />
          <FacetGroup
            title="Tags"
            facet={facets.tags}
            selected={filter.tag}
            onSelect={(v) => setKey("tag", v)}
          />
          <FacetGroup
            title="Entities"
            facet={facets.entities}
            selected={filter.entity}
            onSelect={(v) => setKey("entity", v)}
          />
          <FacetGroup
            title="Documents"
            facet={facets.documents}
            selected={filter.doc_id}
            onSelect={(v) => setKey("doc_id", v)}
          />
        </aside>

        <section className="explorer-results">
          <div className="explorer-toolbar">
            <input
              className="explorer-search"
              placeholder="Search chunk text…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <span className="muted">{total} results</span>
          </div>
          {activeFilterChips.length > 0 && (
            <div className="chip-row" style={{ marginBottom: "0.5rem" }}>
              {activeFilterChips.map((f) => (
                <button
                  key={f.key}
                  className="chip chip-active"
                  onClick={() => clearKey(f.key)}
                  title="Click to remove"
                >
                  {f.label}: {f.value} ✕
                </button>
              ))}
            </div>
          )}
          {loading && <p className="muted">Loading…</p>}
          {error && <p className="muted">{error}</p>}
          {!loading && !error && chunks.length === 0 && <p className="muted">No chunks match.</p>}
          <div className="chunk-list">
            {chunks.map((c) => (
              <div key={c.id} className="chunk-card">
                <div className="chunk-meta">
                  <span className="chip chip-muted">{c.category}</span>
                  <span className="muted">{c.doc_id}</span>
                  {c.breadcrumb && <span className="muted">· {c.breadcrumb}</span>}
                  {c.page_start && (
                    <span className="muted">
                      · p.{c.page_start}
                      {c.page_end && c.page_end !== c.page_start ? `–${c.page_end}` : ""}
                    </span>
                  )}
                </div>
                <div className="chunk-text">
                  <Highlight text={c.text.slice(0, 480)} needle={debouncedQ} />
                  {c.text.length > 480 ? "…" : ""}
                </div>
                <div className="chunk-actions">
                  <button className="btn btn-sm" onClick={() => setPreview(c)}>Preview</button>
                  <button className="btn btn-sm btn-primary" onClick={() => onAskAboutChunk(c)}>
                    Ask about this
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      {preview && (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>{preview.doc_id}</h3>
              <button className="btn btn-sm" onClick={() => setPreview(null)}>Close</button>
            </div>
            <div className="modal-meta">
              <span className="chip chip-muted">{preview.category}</span>
              {preview.breadcrumb && <span className="muted">{preview.breadcrumb}</span>}
              {preview.page_start && (
                <span className="muted">
                  page {preview.page_start}
                  {preview.page_end && preview.page_end !== preview.page_start ? `–${preview.page_end}` : ""}
                </span>
              )}
            </div>
            <pre className="modal-text">{preview.text}</pre>
            {preview.entities.length > 0 && (
              <div className="chip-row">
                {preview.entities.map((e, i) => (
                  <span key={i} className="chip chip-muted">{e}</span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function FacetGroup({
  title,
  facet,
  selected,
  onSelect,
}: {
  title: string;
  facet: Record<string, number> | undefined;
  selected?: string;
  onSelect: (value: string) => void;
}) {
  const entries = Object.entries(facet || {});
  if (entries.length === 0) return null;
  return (
    <div className="facet-group">
      <h5>{title}</h5>
      <ul>
        {entries.slice(0, 12).map(([value, count]) => (
          <li key={value}>
            <button
              className={`facet-item ${selected === value ? "is-active" : ""}`}
              onClick={() => onSelect(value)}
            >
              <span>{value}</span>
              <span className="muted">{count}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
