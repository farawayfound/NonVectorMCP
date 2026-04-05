import { useState, useRef } from "react";

interface Props {
  onUpload: (file: File) => Promise<void>;
}

const ALLOWED = [".pdf", ".txt", ".docx", ".pptx", ".csv"];

export function UploadZone({ onUpload }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    const ext = "." + file.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED.includes(ext)) {
      setError(`Unsupported file type: ${ext}`);
      return;
    }
    setError("");
    setUploading(true);
    try {
      await onUpload(file);
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      className={`upload-zone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
      }}
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ALLOWED.join(",")}
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleFile(file);
          e.target.value = "";
        }}
      />
      {uploading ? (
        <p>Uploading...</p>
      ) : (
        <p>Drop a file here or click to upload<br /><small>{ALLOWED.join(", ")}</small></p>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}
