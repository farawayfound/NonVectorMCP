import type { Document } from "../types";

interface Props {
  doc: Document;
  onDelete: (filename: string) => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentCard({ doc, onDelete }: Props) {
  return (
    <div className="document-card">
      <div className="doc-info">
        <span className="doc-name">{doc.filename}</span>
        <span className="doc-meta">{formatSize(doc.size_bytes)} &middot; {doc.suffix}</span>
      </div>
      <button className="btn btn-sm btn-danger" onClick={() => onDelete(doc.filename)}>
        Delete
      </button>
    </div>
  );
}
