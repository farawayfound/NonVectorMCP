import { useState, useEffect, useRef } from "react";
import type { ChatMessage as Msg } from "../types";

interface Props {
  message: Msg;
  /** Hide the collapsible thinking UI (e.g. when thinking is shown in AMA status strip). */
  suppressThinking?: boolean;
}

export function ChatMessage({ message, suppressThinking }: Props) {
  const isUser = message.role === "user";
  const [thinkingOpen, setThinkingOpen] = useState(false);
  const thinkingRef = useRef<HTMLDivElement>(null);
  const hasThinking = !isUser && !!message.thinking && !suppressThinking;
  const isThinkingLive = hasThinking && !message.thinkingDone;

  // While thinking is live/streaming, keep it open; collapse when done
  useEffect(() => {
    if (isThinkingLive) {
      setThinkingOpen(true);
    } else if (message.thinkingDone) {
      setThinkingOpen(false);
    }
  }, [isThinkingLive, message.thinkingDone]);

  // Auto-scroll thinking content while streaming
  useEffect(() => {
    if (isThinkingLive && thinkingRef.current) {
      thinkingRef.current.scrollTop = thinkingRef.current.scrollHeight;
    }
  }, [message.thinking, isThinkingLive]);

  return (
    <div className={`chat-message ${isUser ? "user" : "assistant"}`}>
      <div className="message-role">{isUser ? "You" : "ChunkyPotato"}</div>
      {hasThinking && (
        <div className="thinking-block">
          <button
            className="thinking-toggle"
            onClick={() => setThinkingOpen((o) => !o)}
          >
            <span className={`thinking-arrow ${thinkingOpen ? "open" : ""}`}>&#9654;</span>
            {" "}{isThinkingLive ? "Thinking…" : "Thinking"}
          </button>
          {thinkingOpen && (
            <div
              ref={thinkingRef}
              className={`thinking-content ${isThinkingLive ? "thinking-live" : ""}`}
            >
              {message.thinking}
            </div>
          )}
        </div>
      )}
      <div className="message-content">{message.content || "\u00A0"}</div>
    </div>
  );
}
