import { useState, useCallback, useRef } from "react";
import { streamChat } from "../api/client";
import type { ChatMessage } from "../types";

export type ChatPhase = "idle" | "sending" | "searching" | "thinking" | "answering";

/** Minimum milliseconds each phase must stay visible before transitioning.
 *  Kept tiny so a fast warm backend is not artificially gated — just enough
 *  to prevent the stepper from flashing between stages on instant responses. */
const PHASE_MIN_MS: Record<ChatPhase, number> = {
  idle: 0,
  sending: 150,
  searching: 150,
  thinking: 0,
  answering: 0,
};

export function useChat(endpoint: "/chat/ask" | "/chat/documents" = "/chat/ask") {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const abortRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (query: string, extra?: Record<string, unknown>) => {
      const userMsg: ChatMessage = { role: "user", content: query };
      setMessages((prev) => [...prev, userMsg]);
      setStreaming(true);
      setPhase("sending");

      const assistantMsg: ChatMessage = { role: "assistant", content: "", thinking: "" };
      setMessages((prev) => [...prev, assistantMsg]);

      // Track phase timing so each phase is visible for its minimum duration
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
        for await (const event of streamChat(endpoint, body)) {
          if (event.phase) {
            if (event.phase === "search") {
              await transitionPhase("searching");
            } else if (event.phase === "generate") {
              await transitionPhase("thinking");
            } else if (event.phase === "answering") {
              await transitionPhase("answering");
              answering = true;
              // Mark thinking as done so the component collapses it
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant" && last.thinking) {
                  updated[updated.length - 1] = { ...last, thinkingDone: true };
                }
                return updated;
              });
            }
          }
          if (event.thinking) {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
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
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last.role === "assistant" && last.thinking) {
                  updated[updated.length - 1] = { ...last, thinkingDone: true };
                }
                return updated;
              });
            }
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last.role === "assistant") {
                updated[updated.length - 1] = { ...last, content: last.content + event.text };
              }
              return updated;
            });
          }
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
        // Finalize the assistant message — runs no matter how the stream ended.
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            const patched = { ...last };

            // Always mark thinking as complete so the toggle never sticks on "Thinking…"
            if (patched.thinking) {
              patched.thinkingDone = true;
            }

            // If the model produced only thinking content with no visible response
            // (e.g. Ollama auto-separated and model spent all tokens on reasoning),
            // move thinking into the response area so the user always sees something.
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
    setMessages([]);
    setPhase("idle");
  }, []);

  return { messages, streaming, phase, send, clear };
}
