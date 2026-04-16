import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { useChat } from "../hooks/useChat";
import { ChatMessage as ChatMessageView } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatProgress } from "../components/ChatProgress";
import { RequestAccessModal } from "../components/RequestAccessModal";
import { SuggestionCarousel } from "../components/SuggestionCarousel";
import type { SuggestionCarouselVisualMode } from "../components/SuggestionCarousel";
import { getChatSuggestions } from "../api/client";
import type { ChatMessage } from "../types";

function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function groupTurns(messages: ChatMessage[]): { user: ChatMessage; assistant: ChatMessage }[] {
  const out: { user: ChatMessage; assistant: ChatMessage }[] = [];
  for (let i = 0; i + 1 < messages.length; i += 2) {
    const u = messages[i];
    const a = messages[i + 1];
    if (u?.role === "user" && a?.role === "assistant") out.push({ user: u, assistant: a });
  }
  return out;
}

export function AskMeAnything() {
  const { messages, streaming, phase, send, clear: clearChat } = useChat("/chat/ask");
  const bottomRef = useRef<HTMLDivElement>(null);
  const [suggestionPool, setSuggestionPool] = useState<string[]>([]);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [showAccessModal, setShowAccessModal] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  const [carouselVisual, setCarouselVisual] = useState<"intro" | "idle">("intro");
  const [carouselSession, setCarouselSession] = useState(0);
  const [pickHero, setPickHero] = useState<{ slot: number; text: string } | null>(null);
  const [scatterAll, setScatterAll] = useState(false);
  const [threadExiting, setThreadExiting] = useState(false);
  const [firstTurnKind, setFirstTurnKind] = useState<null | "carousel" | "typed">(null);
  const [flyInTurnIndex, setFlyInTurnIndex] = useState<number | null>(null);
  const prevTurnsLenRef = useRef(0);

  const turns = useMemo(() => groupTurns(messages), [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, turns.length, streaming, phase]);

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

  useEffect(() => {
    if (reduceMotion || suggestionPool.length === 0) {
      setCarouselVisual("idle");
      return;
    }
    setCarouselVisual("intro");
    const t = window.setTimeout(() => setCarouselVisual("idle"), 760);
    return () => window.clearTimeout(t);
  }, [suggestionPool, reduceMotion, carouselSession]);

  useEffect(() => {
    const n = turns.length;
    if (n <= prevTurnsLenRef.current) {
      prevTurnsLenRef.current = n;
      return;
    }
    prevTurnsLenRef.current = n;
    if (n <= 1) return;
    setFlyInTurnIndex(n - 1);
    const t = window.setTimeout(() => setFlyInTurnIndex(null), 720);
    return () => window.clearTimeout(t);
  }, [turns.length]);

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

  const baseSend = useCallback(
    async (query: string) => {
      if (rateLimited) {
        setShowAccessModal(true);
        return;
      }
      await send(query);
    },
    [send, rateLimited],
  );

  const handlePickFromCarousel = useCallback(
    (q: string, slot: number) => {
      if (rateLimited) {
        setShowAccessModal(true);
        return;
      }
      if (reduceMotion) {
        setFirstTurnKind("carousel");
        void baseSend(q);
        return;
      }
      setFirstTurnKind("carousel");
      setPickHero({ slot, text: q });
      window.setTimeout(() => {
        void baseSend(q);
        setPickHero(null);
      }, 700);
    },
    [rateLimited, reduceMotion, baseSend],
  );

  const handleSend = useCallback(
    (query: string) => {
      if (rateLimited) {
        setShowAccessModal(true);
        return;
      }
      if (reduceMotion) {
        if (messages.length === 0) setFirstTurnKind("typed");
        void baseSend(query);
        return;
      }
      const isFirst = messages.length === 0;
      if (isFirst && suggestionPool.length > 0 && !pickHero) {
        setFirstTurnKind("typed");
        setScatterAll(true);
        window.setTimeout(() => {
          void baseSend(query);
          setScatterAll(false);
        }, 580);
        return;
      }
      void baseSend(query);
    },
    [rateLimited, messages.length, suggestionPool.length, pickHero, baseSend, reduceMotion],
  );

  const handleClear = useCallback(() => {
    if (messages.length === 0) return;
    setPickHero(null);
    setScatterAll(false);
    if (reduceMotion) {
      clearChat();
      setFirstTurnKind(null);
      setThreadExiting(false);
      prevTurnsLenRef.current = 0;
      setCarouselSession((s) => s + 1);
      return;
    }
    setThreadExiting(true);
    window.setTimeout(() => {
      clearChat();
      setThreadExiting(false);
      setFirstTurnKind(null);
      prevTurnsLenRef.current = 0;
      setCarouselSession((s) => s + 1);
    }, 480);
  }, [messages.length, reduceMotion, clearChat]);

  const empty = messages.length === 0;

  let carouselMode: SuggestionCarouselVisualMode = "idle";
  if (pickHero) carouselMode = "pickHero";
  else if (scatterAll) carouselMode = "scatterAll";
  else if (carouselVisual === "intro") carouselMode = "intro";

  return (
    <div className="chat-page">
      <div className="chat-header">
        <h2>Ask Me Anything</h2>
        {messages.length > 0 && (
          <button type="button" onClick={handleClear} className="btn btn-sm">
            Clear
          </button>
        )}
      </div>

      <div className={`chat-messages${empty ? " chat-messages--empty-carousel" : ""}`}>
        {empty && (
          <div className="chat-empty chat-empty--carousel">
            <p>Ask anything about my background, skills, or projects.</p>
            {suggestionPool.length > 0 && !reduceMotion && (
              <SuggestionCarousel
                key={carouselSession}
                pool={suggestionPool}
                onPick={handlePickFromCarousel}
                paused={streaming || rateLimited || !!pickHero || scatterAll}
                visualMode={carouselMode}
                pickHeroSlot={pickHero?.slot ?? null}
              />
            )}
            {suggestionPool.length > 0 && reduceMotion && (
              <div className="suggestions">
                {suggestionPool.slice(0, 6).map((q, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setFirstTurnKind("carousel");
                      void baseSend(q);
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.length > 0 && (
          <div className={`ama-thread${threadExiting ? " ama-thread--exit" : ""}`}>
            {turns.map((t, i) => {
              const isLastTurn = i === turns.length - 1;
              const qClass =
                "ama-q-card" +
                (i === 0 && firstTurnKind === "typed" ? " ama-q-card--from-input-bar" : "") +
                (i > 0 && flyInTurnIndex === i ? " ama-q-card--from-input" : "");
              return (
                <div key={`${i}-${t.user.content.slice(0, 40)}`} className="ama-turn">
                  <div className={qClass}>{t.user.content}</div>
                  {streaming && isLastTurn && phase !== "idle" && (
                    <div className="ama-progress-track ama-progress-track--slide-open">
                      <div className="ama-progress-inner">
                        <ChatProgress
                          phase={phase}
                          thinking={t.assistant.thinking || ""}
                          minimizeThinking={
                            phase === "answering" && (t.assistant.content?.length ?? 0) > 0
                          }
                        />
                      </div>
                    </div>
                  )}
                  <ChatMessageView
                    message={t.assistant}
                    suppressThinking={streaming && isLastTurn}
                  />
                </div>
              );
            })}
          </div>
        )}

        {rateLimited && !showAccessModal && (
          <div className="rate-limit-banner">
            <p>You've reached the free question limit.</p>
            <button
              type="button"
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
        placeholder={
          rateLimited ? "Request access to ask more questions..." : "Ask about my experience..."
        }
      />

      {showAccessModal && (
        <RequestAccessModal onClose={() => setShowAccessModal(false)} />
      )}
    </div>
  );
}
