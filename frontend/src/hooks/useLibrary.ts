import { useCallback, useEffect, useRef, useState } from "react";
import {
  getLibraryTasks,
  getLibraryTask,
  submitResearch,
  approveLibraryTask,
  cancelLibraryTask,
  deleteLibraryTask,
  subscribeTaskStatus,
} from "../api/client";

export interface LibraryTask {
  id: string;
  user_id: string;
  prompt: string;
  status: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  sources_found: number;
  artifact_path: string | null;
  error: string | null;
  artifact?: string | null;
  sources?: { url: string; title: string }[];
}

export function useLibrary() {
  const [tasks, setTasks] = useState<LibraryTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleanupRefs = useRef<Map<string, () => void>>(new Map());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getLibraryTasks();
      setTasks(res.tasks || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const submit = useCallback(async (prompt: string, options?: Record<string, unknown>) => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await submitResearch(prompt, options);
      await refresh();
      return res;
    } catch (e: any) {
      setError(e.message);
      throw e;
    } finally {
      setSubmitting(false);
    }
  }, [refresh]);

  const fetchTask = useCallback(async (id: string): Promise<LibraryTask | null> => {
    try {
      return await getLibraryTask(id);
    } catch {
      return null;
    }
  }, []);

  const importOne = useCallback(async (id: string) => {
    try {
      const res = await approveLibraryTask(id);
      await refresh();
      return res;
    } catch (e: any) {
      setError(e.message);
      throw e;
    }
  }, [refresh]);

  const importSelected = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return { results: [] as any[] };
    setError(null);
    // Sequential imports to avoid concurrent SQLite writes and index-file race conditions.
    const results: { id: string; ok: boolean; value: any; error: string | null }[] = [];
    let failCount = 0;
    let firstError: string | null = null;
    for (const id of ids) {
      try {
        const value = await approveLibraryTask(id);
        results.push({ id, ok: true, value, error: null });
      } catch (e: any) {
        failCount++;
        if (!firstError) firstError = e?.message || "Could not import task";
        results.push({ id, ok: false, value: null, error: e?.message || null });
      }
    }
    await refresh();
    if (failCount > 0) {
      setError(
        failCount === ids.length
          ? firstError || "Could not import tasks"
          : `${failCount} of ${ids.length} tasks could not be imported`,
      );
    }
    return { results };
  }, [refresh]);

  const deleteSelected = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;
    setError(null);
    for (const id of ids) {
      const cleanup = cleanupRefs.current.get(id);
      if (cleanup) {
        cleanup();
        cleanupRefs.current.delete(id);
      }
    }
    setTasks((prev) => prev.filter((t) => !ids.includes(t.id)));
    const settled = await Promise.allSettled(ids.map((id) => deleteLibraryTask(id)));
    const failed = settled.filter((r) => r.status === "rejected");
    await refresh();
    if (failed.length > 0) {
      const first = failed[0] as PromiseRejectedResult;
      setError(
        failed.length === ids.length
          ? first.reason?.message || "Could not delete tasks"
          : `${failed.length} of ${ids.length} tasks could not be deleted`,
      );
    }
  }, [refresh]);

  const cancelSelected = useCallback(async (ids: string[]) => {
    if (ids.length === 0) return;
    setError(null);
    for (const id of ids) {
      const cleanup = cleanupRefs.current.get(id);
      if (cleanup) {
        cleanup();
        cleanupRefs.current.delete(id);
      }
    }
    setTasks((prev) =>
      prev.map((t) => (ids.includes(t.id) ? { ...t, status: "cancelled" } : t)),
    );
    const results = await Promise.allSettled(ids.map((id) => cancelLibraryTask(id)));
    const failed = results.filter((r) => r.status === "rejected");
    await refresh();
    if (failed.length > 0) {
      const first = failed[0] as PromiseRejectedResult;
      const msg =
        failed.length === ids.length
          ? first.reason?.message || "Could not cancel tasks"
          : `${failed.length} of ${ids.length} tasks could not be cancelled`;
      setError(msg);
    }
  }, [refresh]);

  const subscribe = useCallback((taskId: string) => {
    if (cleanupRefs.current.has(taskId)) return;

    const cleanup = subscribeTaskStatus(
      taskId,
      (data) => {
        setTasks((prev) =>
          prev.map((t) =>
            t.id === taskId
              ? { ...t, status: data.status, sources_found: data.sources_found || t.sources_found }
              : t,
          ),
        );
      },
      () => {
        cleanupRefs.current.delete(taskId);
        refresh();
      },
    );
    cleanupRefs.current.set(taskId, cleanup);
  }, [refresh]);

  useEffect(() => {
    return () => {
      cleanupRefs.current.forEach((fn) => fn());
      cleanupRefs.current.clear();
    };
  }, []);

  // Auto-subscribe to active tasks
  useEffect(() => {
    for (const t of tasks) {
      if (["queued", "crawling", "synthesizing"].includes(t.status)) {
        subscribe(t.id);
      }
    }
  }, [tasks, subscribe]);

  return {
    tasks,
    loading,
    submitting,
    error,
    refresh,
    submit,
    fetchTask,
    importOne,
    importSelected,
    deleteSelected,
    cancelSelected,
  };
}
