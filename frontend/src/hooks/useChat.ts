import { useState, useCallback, useRef } from "react";
import { streamChat } from "../api/client";
import type { ChatMessage } from "../types";

export function useChat(endpoint: "/chat/ask" | "/chat/documents" = "/chat/ask") {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (query: string, extra?: Record<string, unknown>) => {
      const userMsg: ChatMessage = { role: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      setStreaming(true);

      const assistantMsg: ChatMessage = { role: "assistant", content: "" };
      setMessages((prev) => [...prev, assistantMsg]);

      try {
        const body: Record<string, unknown> = { query, ...extra };
        if (endpoint === "/chat/documents") {
          body.messages = [...messages, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          }));
        }

        for await (const chunk of streamChat(endpoint, body)) {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: last.content + chunk };
            }
            return updated;
          });
        }
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last.role === "assistant") {
            const base = last.content.trim();
            updated[updated.length - 1] = {
              ...last,
              content: base
                ? `${last.content}\n\n[Error: ${detail}]`
                : `Sorry, something went wrong.\n\n${detail}`,
            };
          }
          return updated;
        });
      } finally {
        setStreaming(false);
      }
    },
    [endpoint, messages],
  );

  const clear = useCallback(() => {
    setMessages([]);
  }, []);

  return { messages, streaming, send, clear };
}
