import { useRef, useEffect, useState, useCallback } from "react";
import { useChat } from "../hooks/useChat";
import { ChatMessage } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatProgress } from "../components/ChatProgress";
import { RequestAccessModal } from "../components/RequestAccessModal";
import { SuggestionCarousel } from "../components/SuggestionCarousel";
import { getChatSuggestions } from "../api/client";

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function AskMeAnything() {
  const { messages, streaming, phase, send, clear } = useChat("/chat/ask");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [suggestionPool, setSuggestionPool] = useState<string[]>([]);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [showAccessModal, setShowAccessModal] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => setReduceMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    getChatSuggestions()
      .then((data) => {
        const pool = data.suggestions || [];
        setSuggestionPool(
          pool.length > 0
            ? shuffle(pool)
            : ["Tell me about your professional background"],
        );
      })
      .catch(() => {
        setSuggestionPool(["Tell me about your professional background"]);
      });
  }, []);

  // Detect rate limit from chat error messages (429 response)
  useEffect(() => {
    if (rateLimited) return;
    const lastMsg = messages[messages.length - 1];
    if (
      lastMsg?.role === "assistant" &&
      (lastMsg.content.includes("rate_limited") || lastMsg.content.includes("(429)"))
    ) {
      setRateLimited(true);
      setShowAccessModal(true);
    }
  }, [messages, rateLimited]);

  const handleSend = useCallback(
    (query: string) => {
      if (rateLimited) {
        setShowAccessModal(true);
        return;
      }
      send(query);
    },
    [send, rateLimited],
  );

  const empty = messages.length === 0;

  return (
    <div className="chat-page">
      <div className="chat-header">
        <h2>Ask Me Anything</h2>
        {messages.length > 0 && (
          <button onClick={clear} className="btn btn-sm">Clear</button>
        )}
      </div>

      <div className={`chat-messages${empty ? " chat-messages--empty-carousel" : ""}`}>
        {empty && (
          <div className="chat-empty chat-empty--carousel">
            <p>Ask anything about my background, skills, or projects.</p>
            {suggestionPool.length > 0 && !reduceMotion && (
              <SuggestionCarousel
                pool={suggestionPool}
                onSelect={handleSend}
                paused={streaming || rateLimited}
              />
            )}
            {suggestionPool.length > 0 && reduceMotion && (
              <div className="suggestions">
                {suggestionPool.slice(0, 6).map((q, i) => (
                  <button key={i} type="button" onClick={() => handleSend(q)}>
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage key={i} message={msg} />
        ))}
        {streaming && <ChatProgress phase={phase} />}
        {rateLimited && !showAccessModal && (
          <div className="rate-limit-banner">
            <p>You've reached the free question limit.</p>
            <button
              onClick={() => setShowAccessModal(true)}
              className="btn btn-sm btn-primary"
            >
              Request Access to Continue
            </button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <ChatInput
        onSend={handleSend}
        disabled={streaming}
        placeholder={rateLimited ? "Request access to ask more questions..." : "Ask about my experience..."}
      />

      {showAccessModal && (
        <RequestAccessModal onClose={() => setShowAccessModal(false)} />
      )}
    </div>
  );
}
