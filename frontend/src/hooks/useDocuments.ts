import { useState, useCallback } from "react";
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  getDocumentStats,
  buildIndex,
  type BuildIndexOptions,
  getIndexStatus,
  getChunkingConfig,
  updateChunkingConfig,
  getTokenMetrics,
  getAgentConfig,
  updateAgentConfig,
  deleteAllDocuments,
  getPreserveFlag,
  setPreserveFlag,
} from "../api/client";
import type { Document, IndexStatus, ChunkingConfig, TokenMetrics } from "../types";

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(false);
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [chunkingConfig, setChunkingConfig] = useState<ChunkingConfig | null>(null);
  const [metrics, setMetrics] = useState<TokenMetrics | null>(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [agentConfig, setAgentConfig] = useState<{
    system_prompt: string;
    system_rules: string;
    default_system_prompt: string;
    default_system_rules: string;
  } | null>(null);
  const [preserveData, setPreserveData] = useState<{
    preserve: boolean;
    session_expires_at: string | null;
  } | null>(null);

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

  const startIndex = useCallback(async (opts: BuildIndexOptions = {}) => {
    const result = await buildIndex(opts);
    await refreshIndex();
    return result;
  }, []);

  const refreshIndex = useCallback(async () => {
    try {
      const status = await getIndexStatus();
      setIndexStatus(status);
    } catch {
      // no-op
    }
  }, []);

  const refreshConfig = useCallback(async () => {
    try {
      const cfg = await getChunkingConfig();
      setChunkingConfig(cfg);
    } catch {
      // no-op
    }
  }, []);

  const saveConfig = useCallback(async (config: Partial<ChunkingConfig>) => {
    const saved = await updateChunkingConfig(config as Record<string, unknown>);
    setChunkingConfig(saved);
  }, []);

  const refreshMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const m = await getTokenMetrics();
      setMetrics(m);
    } catch {
      // no-op
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  const refreshAgentConfig = useCallback(async () => {
    try {
      const cfg = await getAgentConfig();
      setAgentConfig(cfg);
    } catch {
      // no-op
    }
  }, []);

  const saveAgentConfig = useCallback(async (config: Record<string, unknown>) => {
    const saved = await updateAgentConfig(config);
    // Re-fetch to get defaults too
    await refreshAgentConfig();
    return saved;
  }, [refreshAgentConfig]);

  const deleteAll = useCallback(async () => {
    await deleteAllDocuments();
    setDocuments([]);
    setIndexStatus(null);
    setMetrics(null);
  }, []);

  const refreshPreserve = useCallback(async () => {
    try {
      const flag = await getPreserveFlag();
      setPreserveData(flag);
    } catch {
      // no-op
    }
  }, []);

  const savePreserve = useCallback(async (preserve: boolean) => {
    const result = await setPreserveFlag(preserve);
    await refreshPreserve();
    return result;
  }, [refreshPreserve]);

  return {
    documents, loading, indexStatus,
    chunkingConfig, metrics, metricsLoading,
    agentConfig, preserveData,
    refresh, upload, remove, deleteAll,
    startIndex, refreshIndex,
    refreshConfig, saveConfig, refreshMetrics,
    refreshAgentConfig, saveAgentConfig,
    refreshPreserve, savePreserve,
  };
}
