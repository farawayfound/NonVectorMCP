import { useState, useCallback } from "react";
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  getDocumentStats,
  buildIndex,
  getIndexStatus,
} from "../api/client";
import type { Document, IndexStatus } from "../types";

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listDocuments();
      setDocuments(data.documents);
    } catch {
      // no-op if not authenticated
    } finally {
      setLoading(false);
    }
  }, []);

  const upload = useCallback(
    async (file: File) => {
      await uploadDocument(file);
      await refresh();
    },
    [refresh],
  );

  const remove = useCallback(
    async (filename: string) => {
      await deleteDocument(filename);
      await refresh();
    },
    [refresh],
  );

  const startIndex = useCallback(async () => {
    await buildIndex();
    await refreshIndex();
  }, []);

  const refreshIndex = useCallback(async () => {
    try {
      const status = await getIndexStatus();
      setIndexStatus(status);
    } catch {
      // no-op
    }
  }, []);

  return { documents, loading, indexStatus, refresh, upload, remove, startIndex, refreshIndex };
}
