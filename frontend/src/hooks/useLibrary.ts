import { useCallback, useEffect, useRef, useState } from "react";
import {
  getLibraryTasks,
  getLibraryTask,
  submitResearch,
  approveLibraryTask,
  rejectLibraryTask,
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

  const approve = useCallback(async (id: string) => {
    try {
      const res = await approveLibraryTask(id);
      await refresh();
      return res;
    } catch (e: any) {
      setError(e.message);
      throw e;
    }
  }, [refresh]);

  const reject = useCallback(async (id: string) => {
    try {
      await rejectLibraryTask(id);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    try {
      await deleteLibraryTask(id);
      await refresh();
    } catch (e: any) {
      setError(e.message);
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
    approve,
    reject,
    remove,
  };
}
