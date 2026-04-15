import { useState, useEffect } from "react";
import type { ChunkingConfig as Config } from "../types";

interface Props {
  config: Config | null;
  onSave: (config: Partial<Config>) => Promise<void>;
  disabled?: boolean;
  /** When true, shows a fixed heading and fields (Workspace Settings tab). */
  alwaysExpanded?: boolean;
}

export function ChunkingConfig({ config, onSave, disabled, alwaysExpanded }: Props) {
  const [open, setOpen] = useState(false);
  const [chunkSize, setChunkSize] = useState(300);
  const [overlap, setOverlap] = useState(50);
  const [nlpTagging, setNlpTagging] = useState(true);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (config) {
      setChunkSize(config.chunk_size);
      setOverlap(config.chunk_overlap);
      setNlpTagging(config.enable_nlp_tagging);
      setDirty(false);
    }
  }, [config]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        chunk_size: chunkSize,
        chunk_overlap: overlap,
        enable_nlp_tagging: nlpTagging,
      });
      setDirty(false);
    } finally {
      setSaving(false);
    }
  };

  const markDirty = () => setDirty(true);

  const expanded = alwaysExpanded || open;

  return (
    <div className={`chunking-config ${alwaysExpanded ? "chunking-config--static" : ""}`}>
      {alwaysExpanded ? (
        <h3 style={{ margin: 0 }}>Chunking Settings</h3>
      ) : (
        <button
          className="chunking-config-toggle"
          onClick={() => setOpen(!open)}
          type="button"
        >
          <span className={`chunking-chevron ${open ? "open" : ""}`}>&#9654;</span>
          Chunking Settings
        </button>
      )}

      <div className={`chunking-config-body ${expanded ? "open" : ""}`}>
        <div className="config-field">
          <div className="config-field-header">
            <label>Chunk Size (tokens)</label>
            <span className="config-value">{chunkSize}</span>
          </div>
          <input
            type="range"
            min={50}
            max={2000}
            step={10}
            value={chunkSize}
            onChange={(e) => { setChunkSize(+e.target.value); markDirty(); }}
            disabled={disabled}
          />
          <div className="config-range-labels">
            <span>50</span>
            <span>2000</span>
          </div>
        </div>

        <div className="config-field">
          <div className="config-field-header">
            <label>Overlap (tokens)</label>
            <span className="config-value">{overlap}</span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.min(500, chunkSize - 10)}
            step={5}
            value={overlap}
            onChange={(e) => { setOverlap(+e.target.value); markDirty(); }}
            disabled={disabled}
          />
          <div className="config-range-labels">
            <span>0</span>
            <span>{Math.min(500, chunkSize - 10)}</span>
          </div>
        </div>

        <div className="config-field config-toggle-row">
          <label>NLP Metadata Tagging</label>
          <button
            type="button"
            role="switch"
            aria-checked={nlpTagging}
            className={`toggle-switch ${nlpTagging ? "on" : ""}`}
            onClick={() => { setNlpTagging(!nlpTagging); markDirty(); }}
            disabled={disabled}
          >
            <span className="toggle-knob" />
          </button>
        </div>

        {dirty && (
          <button
            className="btn btn-primary btn-sm config-save-btn"
            onClick={handleSave}
            disabled={saving || disabled}
          >
            {saving ? "Saving..." : "Save & Rebuild Index"}
          </button>
        )}
        {dirty && (
          <p className="muted config-hint">
            Changes take effect on next index build.
          </p>
        )}
      </div>
    </div>
  );
}
