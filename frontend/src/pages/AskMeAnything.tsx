import { useRef, useEffect, useState, useCallback, useMemo, useLayoutEffect } from "react";
import { useChat } from "../hooks/useChat";
import { ChatMessage as ChatMessageView } from "../components/ChatMessage";
import { ChatInput } from "../components/ChatInput";
import { ChatProgress } from "../components/ChatProgress";
import { RequestAccessModal } from "../components/RequestAccessModal";
import { SuggestionCarousel } from "../components/SuggestionCarousel";
import type { SuggestionCarouselVisualMode } from "../components/SuggestionCarousel";
import { getChatSuggestions } from "../api/client";
import type { ChatMessage } from "../types";
import { usePageTransition } from "../components/PageTransitionContext";

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

type FlightRect = { left: number; top: number; width: number; height: number };
type FlightState = { text: string; from: FlightRect; source: "carousel" | "typed" };

export function AskMeAnything() {
  const { messages, streaming, phase, send, clear: clearChat } = useChat("/chat/ask");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputBarRef = useRef<HTMLDivElement>(null);
  const firstQRef = useRef<HTMLDivElement>(null);
  const flightElRef = useRef<HTMLDivElement>(null);
  const flightAnimKeyRef = useRef<string>("");

  const [suggestionPool, setSuggestionPool] = useState<string[]>([]);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [showAccessModal, setShowAccessModal] = useState(false);
  const [rateLimited, setRateLimited] = useState(false);

  const { isExiting } = usePageTransition();
  const [pageReady, setPageReady] = useState(false);
  const [carouselVisual, setCarouselVisual] = useState<"intro" | "idle">("intro");
  const [carouselSession, setCarouselSession] = useState(0);
  const [pickHero, setPickHero] = useState<{ slot: number; text: string } | null>(null);
  const [scatterAll, setScatterAll] = useState(false);
  const [threadExiting, setThreadExiting] = useState(false);
  const [firstTurnKind, setFirstTurnKind] = useState<null | "carousel" | "typed">(null);
  const [flyInTurnIndex, setFlyInTurnIndex] = useState<number | null>(null);
  const [flight, setFlight] = useState<FlightState | null>(null);
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

  // Wait for the page flip to finish before starting the carousel intro
  useEffect(() => {
    if (isExiting) {
      setPageReady(false);
      return;
    }
    // Small delay to let the flip-in animation complete
    const t = window.setTimeout(() => setPageReady(true), 80);
    return () => window.clearTimeout(t);
  }, [isExiting]);

  useEffect(() => {
    if (!pageReady || reduceMotion || suggestionPool.length === 0) {
      setCarouselVisual("idle");
      return;
    }
    setCarouselVisual("intro");
    const t = window.setTimeout(() => setCarouselVisual("idle"), 760);
    return () => window.clearTimeout(t);
  }, [suggestionPool, reduceMotion, carouselSession, pageReady]);

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

  useLayoutEffect(() => {
    if (!flight || messages.length < 2) {
      if (!flight) flightAnimKeyRef.current = "";
      return;
    }
    const fly = flightElRef.current;
    const target = firstQRef.current;
    if (!fly || !target) return;

    const flightSource = flight.source;
    const animKey = `${flightSource}-${flight.from.left},${flight.from.top},${flight.text}`;
    if (flightAnimKeyRef.current === animKey) return;
    flightAnimKeyRef.current = animKey;

    const to = target.getBoundingClientRect();
    const f = flight.from;

    fly.style.position = "fixed";
    fly.style.left = `${f.left}px`;
    fly.style.top = `${f.top}px`;
    fly.style.width = `${f.width}px`;
    fly.style.height = `${f.height}px`;
    fly.style.transition = "none";
    fly.classList.remove("ama-prompt-flight--at-target");
    void fly.offsetWidth;

    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      window.clearTimeout(safety);
      fly.removeEventListener("transitionend", onEnd);
      flightAnimKeyRef.current = "";
      setFlight(null);
      if (flightSource === "carousel") {
        setPickHero(null);
      }
    };

    const onEnd = () => finish();

    const safety = window.setTimeout(finish, 1100);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (finished) return;
        fly.classList.add("ama-prompt-flight--at-target");
        fly.style.transition =
          "left 0.68s cubic-bezier(0.22, 1, 0.36, 1), top 0.68s cubic-bezier(0.22, 1, 0.36, 1), width 0.68s cubic-bezier(0.22, 1, 0.36, 1), height 0.68s cubic-bezier(0.22, 1, 0.36, 1), font-size 0.68s cubic-bezier(0.22, 1, 0.36, 1), padding 0.68s cubic-bezier(0.22, 1, 0.36, 1)";
        fly.style.left = `${to.left}px`;
        fly.style.top = `${to.top}px`;
        fly.style.width = `${to.width}px`;
        fly.style.height = `${to.height}px`;
        fly.addEventListener("transitionend", onEnd, { once: true });
      });
    });

    return () => {
      finished = true;
      window.clearTimeout(safety);
      fly.removeEventListener("transitionend", onEnd);
    };
  }, [flight, messages.length]);

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
    (q: string, slot: number, sourceEl: HTMLButtonElement) => {
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
      flightAnimKeyRef.current = "";
      const fr = sourceEl.getBoundingClientRect();
      setFlight({
        text: q,
        from: { left: fr.left, top: fr.top, width: fr.width, height: fr.height },
        source: "carousel",
      });
      setPickHero({ slot, text: q });
      window.setTimeout(() => {
        void baseSend(q);
      }, 120);
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
      if (isFirst && !pickHero) {
        setFirstTurnKind("typed");
        if (suggestionPool.length > 0) {
          setScatterAll(true);
        }
        if (!reduceMotion && inputBarRef.current) {
          flightAnimKeyRef.current = "";
          const r = inputBarRef.current.getBoundingClientRect();
          setFlight({
            text: query,
            from: { left: r.left, top: r.top, width: r.width, height: r.height },
            source: "typed",
          });
        }
        const scatterMs = suggestionPool.length > 0 ? 560 : 48;
        window.setTimeout(() => {
          void baseSend(query);
          setScatterAll(false);
        }, scatterMs);
        return;
      }
      void baseSend(query);
    },
    [rateLimited, messages.length, suggestionPool.length, pickHero, baseSend, reduceMotion],
  );

  const handleClear = useCallback(() => {
    if (messages.length === 0) return;
    setFlight(null);
    setPickHero(null);
    flightAnimKeyRef.current = "";
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
                (i === 0 && firstTurnKind === "typed" && reduceMotion ? " ama-q-card--from-input-bar" : "") +
                (i > 0 && flyInTurnIndex === i ? " ama-q-card--from-input" : "") +
                (flight && i === 0 ? " ama-q-card--flight-hidden" : "");
              return (
                <div key={`${i}-${t.user.content.slice(0, 40)}`} className="ama-turn">
                  <div ref={i === 0 ? firstQRef : undefined} className={qClass}>
                    {t.user.content}
                  </div>
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
                    assistantMarkdown
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

      {flight && (
        <div
          ref={flightElRef}
          className="ama-prompt-flight"
          style={{
            left: flight.from.left,
            top: flight.from.top,
            width: flight.from.width,
            height: flight.from.height,
          }}
        >
          {flight.text}
        </div>
      )}

      <ChatInput
        ref={inputBarRef}
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
