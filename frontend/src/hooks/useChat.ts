import { useState, useCallback, useRef } from "react";
import { streamChat } from "../api/client";
import type { ChatMessage } from "../types";

export type ChatPhase = "idle" | "sending" | "searching" | "thinking" | "answering";

/** Minimum milliseconds each phase must stay visible before transitioning. */
const PHASE_MIN_MS: Record<ChatPhase, number> = {
  idle: 0,
  sending: 3000,
  searching: 2000,
  thinking: 0,
  answering: 0,
};

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === "AbortError") ||
    (err instanceof Error && err.name === "AbortError")
  );
}

export function useChat(endpoint: "/chat/ask" | "/chat/documents" = "/chat/ask") {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (query: string, extra?: Record<string, unknown>) => {
      abortRef.current?.abort();
      const ac = new AbortController();
      abortRef.current = ac;

      const userMsg: ChatMessage = { role: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      setStreaming(true);
      setPhase("sending");

      const assistantMsg: ChatMessage = { role: "assistant", content: "", thinking: "" };
      setMessages((prev) => [...prev, assistantMsg]);

      let currentPhase: ChatPhase = "sending";
      let phaseStartTime = Date.now();

      const transitionPhase = async (next: ChatPhase) => {
        const minMs = PHASE_MIN_MS[currentPhase];
        const elapsed = Date.now() - phaseStartTime;
        if (elapsed < minMs) {
          await new Promise((r) => setTimeout(r, minMs - elapsed));
        }
        setPhase(next);
        currentPhase = next;
        phaseStartTime = Date.now();
      };

      try {
        const body: Record<string, unknown> = { query, ...extra };
        if (endpoint === "/chat/documents") {
          body.messages = [...messages, userMsg].map((m) => ({
            role: m.role,
            content: m.content,
          }));
        }

        let answering = false;
        for await (const event of streamChat(endpoint, body, { signal: ac.signal })) {
          if (event.phase) {
            if (event.phase === "search") {
              await transitionPhase("searching");
            } else if (event.phase === "generate") {
              await transitionPhase("thinking");
            } else if (event.phase === "answering") {
              await transitionPhase("answering");
              answering = true;
              setMessages((prev) => {
                if (prev.length === 0) return prev;
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant" && last.thinking) {
                  updated[updated.length - 1] = { ...last, thinkingDone: true };
                }
                return updated;
              });
            }
          }
          if (typeof event.thinking === "string" && event.thinking.length > 0) {
            setMessages((prev) => {
              if (prev.length === 0) return prev;
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = {
                  ...last,
                  thinking: (last.thinking || "") + event.thinking,
                };
              }
              return updated;
            });
          }
          if (event.text) {
            if (!answering) {
              await transitionPhase("answering");
              answering = true;
              setMessages((prev) => {
                if (prev.length === 0) return prev;
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === "assistant" && last.thinking) {
                  updated[updated.length - 1] = { ...last, thinkingDone: true };
                }
                return updated;
              });
            }
            setMessages((prev) => {
              if (prev.length === 0) return prev;
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: last.content + event.text };
              }
              return updated;
            });
          }
        }
      } catch (err) {
        if (isAbortError(err)) {
          return;
        }
        const detail = err instanceof Error ? err.message : String(err);
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
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
        if (abortRef.current === ac) {
          abortRef.current = null;
        }
        setMessages((prev) => {
          if (prev.length === 0) return prev;
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            const patched = { ...last };

            if (patched.thinking) {
              patched.thinkingDone = true;
            }

            if (!patched.content.trim() && patched.thinking) {
              patched.content = patched.thinking;
              patched.thinking = "";
            }

            updated[updated.length - 1] = patched;
          }
          return updated;
        });
        setStreaming(false);
        setPhase("idle");
      }
    },
    [endpoint, messages],
  );

  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setPhase("idle");
    setStreaming(false);
  }, []);

  return { messages, streaming, phase, send, clear };
}
