import { useRef, useEffect, useState } from "react";
import { useChat } from "../hooks/useChat";
import { ChatMessage } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { getChatSuggestions } from "../api/client";

export function AskMeAnything() {
  const { messages, streaming, send, clear } = useChat("/chat/ask");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    getChatSuggestions()
      .then((data) => {
        // Pick 4 random suggestions from the pool
        const pool = data.suggestions || [];
        const shuffled = pool.sort(() => Math.random() - 0.5);
        setSuggestions(shuffled.slice(0, 4));
      })
      .catch(() => {
        setSuggestions(["Tell me about your professional background"]);
      });
  }, []);

  return (
    <div className="chat-page">
      <div className="chat-header">
        <h2>Ask Me Anything</h2>
        {messages.length > 0 && (
          <button onClick={clear} className="btn btn-sm">Clear</button>
        )}
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Ask anything about my background, skills, or projects.</p>
            {suggestions.length > 0 && (
              <div className="suggestions">
                {suggestions.map((q, i) => (
                  <button key={i} onClick={() => send(q)}>
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
        <div ref={bottomRef} />
      </div>

      <ChatInput onSend={send} disabled={streaming} placeholder="Ask about my experience..." />
    </div>
  );
}
