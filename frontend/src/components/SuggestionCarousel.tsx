import { useCallback, useEffect, useRef, useState } from "react";

const NUM_SLOTS = 9;
const STEP_DEG = 360 / NUM_SLOTS;
const RADIUS_PX = 280;
const AUTO_DEG_PER_SEC = 14;
const DRAG_DEG_PER_PX = 0.45;
const HOVER_LERP = 0.07;
const MAX_HOVER_TILT = 16;
const READABLE_COS = 0.72;
const EDGE_COS = 0.12;

export type SuggestionCarouselVisualMode = "intro" | "idle" | "pickHero" | "scatterAll";

type Props = {
  pool: string[];
  /** Called when user commits a choice from a readable front card. */
  onPick: (question: string, slotIndex: number) => void;
  paused?: boolean;
  visualMode: SuggestionCarouselVisualMode;
  /** Required when visualMode is `pickHero`. */
  pickHeroSlot?: number | null;
};

function pickFromPool(pool: string[], avoid?: string): string {
  if (pool.length === 0) return "Tell me about your professional background";
  if (pool.length === 1) return pool[0];
  let q = pool[Math.floor(Math.random() * pool.length)];
  let guard = 0;
  while (avoid && q === avoid && guard++ < 8) {
    q = pool[Math.floor(Math.random() * pool.length)];
  }
  return q;
}

function wrapRelDeg(raw: number): number {
  let r = raw % 360;
  if (r > 180) r -= 360;
  if (r < -180) r += 360;
  return r;
}

export function SuggestionCarousel({
  pool,
  onPick,
  paused = false,
  visualMode,
  pickHeroSlot = null,
}: Props) {
  const [texts, setTexts] = useState<string[]>(() =>
    Array.from({ length: NUM_SLOTS }, () => pickFromPool(pool)),
  );
  const pivotRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const spinDegRef = useRef(0);
  const hoverXTiltRef = useRef(0);
  const hoverYTiltRef = useRef(0);
  const targetHoverXRef = useRef(0);
  const targetHoverYRef = useRef(0);
  const prevCosRef = useRef<number[]>(Array.from({ length: NUM_SLOTS }, () => 1));
  const draggingRef = useRef(false);
  const pointerOverStageRef = useRef(false);
  const dragMovedRef = useRef(false);
  const lastPointerXRef = useRef(0);
  const rafRef = useRef(0);
  const lastTRef = useRef<number | null>(null);
  const edgePrimedRef = useRef(false);

  const freeze =
    visualMode === "pickHero" ||
    visualMode === "scatterAll" ||
    visualMode === "intro";

  useEffect(() => {
    if (pool.length === 0) return;
    setTexts(Array.from({ length: NUM_SLOTS }, () => pickFromPool(pool)));
    edgePrimedRef.current = false;
    prevCosRef.current = Array.from({ length: NUM_SLOTS }, () => 1);
  }, [pool]);

  const refreshSlot = useCallback(
    (slot: number) => {
      setTexts((prev) => {
        const next = [...prev];
        next[slot] = pickFromPool(pool, prev[slot]);
        return next;
      });
    },
    [pool],
  );

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const el = stageRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const nx = Math.min(1, Math.max(0, (e.clientX - r.left) / Math.max(r.width, 1)));
      const ny = Math.min(1, Math.max(0, (e.clientY - r.top) / Math.max(r.height, 1)));
      targetHoverXRef.current = (nx - 0.5) * 2 * MAX_HOVER_TILT;
      targetHoverYRef.current = (ny - 0.5) * 2 * MAX_HOVER_TILT * 0.55;

      if (draggingRef.current) {
        const dx = e.clientX - lastPointerXRef.current;
        lastPointerXRef.current = e.clientX;
        spinDegRef.current += dx * DRAG_DEG_PER_PX;
        if (Math.abs(dx) > 0.4) dragMovedRef.current = true;
      }
    };

    const onLeave = () => {
      targetHoverXRef.current = 0;
      targetHoverYRef.current = 0;
    };

    const onUp = () => {
      draggingRef.current = false;
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    const stage = stageRef.current;
    stage?.addEventListener("pointerleave", onLeave);

    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      stage?.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  useEffect(() => {
    const pivot = pivotRef.current;
    if (!pivot) return;

    const tick = (t: number) => {
      if (lastTRef.current === null) lastTRef.current = t;
      const dt = Math.min((t - lastTRef.current) / 1000, 0.05);
      lastTRef.current = t;

      if (!paused && !freeze && !pointerOverStageRef.current && !draggingRef.current) {
        spinDegRef.current += AUTO_DEG_PER_SEC * dt;
      }

      hoverXTiltRef.current +=
        (targetHoverXRef.current - hoverXTiltRef.current) * HOVER_LERP;
      hoverYTiltRef.current +=
        (targetHoverYRef.current - hoverYTiltRef.current) * HOVER_LERP;

      const spin = spinDegRef.current;
      const hx = hoverXTiltRef.current;
      const hy = hoverYTiltRef.current;

      pivot.style.transform =
        `translateZ(-${RADIUS_PX}px) rotateX(${(-hy).toFixed(3)}deg) rotateY(${(spin + hx).toFixed(3)}deg)`;

      for (let i = 0; i < NUM_SLOTS; i++) {
        const rel = wrapRelDeg(i * STEP_DEG + spin);
        const cosF = Math.cos((rel * Math.PI) / 180);
        if (!edgePrimedRef.current) {
          prevCosRef.current[i] = cosF;
        } else if (!freeze) {
          const prev = prevCosRef.current[i];
          if (prev > EDGE_COS && cosF <= EDGE_COS) {
            refreshSlot(i);
          }
          prevCosRef.current[i] = cosF;
        } else {
          prevCosRef.current[i] = cosF;
        }

        const btn = cardRefs.current[i];
        if (btn) {
          const readable = cosF >= READABLE_COS;
          const vis = 0.22 + 0.78 * Math.max(0, Math.min(1, (cosF - 0.08) / 0.92));
          btn.style.opacity = String(vis);
          const allowClick = readable && !paused && !freeze;
          btn.style.pointerEvents = allowClick ? "auto" : "none";
          btn.style.cursor = allowClick ? "pointer" : "default";
        }
      }

      edgePrimedRef.current = true;

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
      lastTRef.current = null;
    };
  }, [paused, refreshSlot, freeze]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (paused || freeze) return;
    const t = e.target as HTMLElement;
    if (t.closest(".suggestion-carousel-card")) return;
    draggingRef.current = true;
    dragMovedRef.current = false;
    lastPointerXRef.current = e.clientX;
    stageRef.current?.setPointerCapture(e.pointerId);
  };

  const onCardPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    draggingRef.current = false;
    dragMovedRef.current = false;
  };

  const onCardClick = (slot: number) => {
    if (paused || freeze || dragMovedRef.current) return;
    const rel = wrapRelDeg(slot * STEP_DEG + spinDegRef.current);
    const cosF = Math.cos((rel * Math.PI) / 180);
    if (cosF < READABLE_COS) return;
    onPick(texts[slot] ?? "", slot);
  };

  const stageClass =
    "suggestion-carousel-stage" +
    (visualMode === "pickHero" ? " suggestion-carousel-stage--pick" : "") +
    (visualMode === "scatterAll" ? " suggestion-carousel-stage--scatter-all" : "") +
    (freeze ? " suggestion-carousel-stage--frozen" : "");

  return (
    <div className="suggestion-carousel" aria-label="Suggested questions carousel">
      <div
        ref={stageRef}
        className={stageClass}
        onPointerEnter={() => {
          pointerOverStageRef.current = true;
        }}
        onPointerLeave={() => {
          pointerOverStageRef.current = false;
        }}
        onPointerDown={onPointerDown}
        role="presentation"
      >
        <div className="suggestion-carousel-pivot-outer">
          <div ref={pivotRef} className="suggestion-carousel-pivot">
            {texts.map((text, i) => {
              const isHero = visualMode === "pickHero" && pickHeroSlot === i;
              const isLeftExit =
                visualMode === "pickHero" &&
                pickHeroSlot != null &&
                i < pickHeroSlot;
              const isRightExit =
                visualMode === "pickHero" &&
                pickHeroSlot != null &&
                i > pickHeroSlot;
              let flipMod = "";
              if (visualMode === "intro") {
                flipMod =
                  i % 2 === 0
                    ? " suggestion-carousel-flip--intro-left"
                    : " suggestion-carousel-flip--intro-right";
              }
              if (isHero) flipMod += " suggestion-carousel-flip--hero";
              else if (isLeftExit) flipMod += " suggestion-carousel-flip--exit-left";
              else if (isRightExit) flipMod += " suggestion-carousel-flip--exit-right";
              else if (visualMode === "scatterAll") {
                flipMod += ` suggestion-carousel-flip--scatter-${i % 4}`;
              }

              return (
                <div
                  key={i}
                  className="suggestion-carousel-cell"
                  style={{ transform: `rotateY(${i * STEP_DEG}deg) translateZ(${RADIUS_PX}px)` }}
                >
                  <div
                    className={`suggestion-carousel-flip${flipMod}`}
                    style={
                      visualMode === "intro"
                        ? ({ animationDelay: `${i * 0.04}s` } as React.CSSProperties)
                        : undefined
                    }
                  >
                    <button
                      type="button"
                      ref={(el) => {
                        cardRefs.current[i] = el;
                      }}
                      className="suggestion-carousel-card"
                      disabled={paused}
                      onPointerDown={onCardPointerDown}
                      onClick={() => onCardClick(i)}
                    >
                      <span className="suggestion-carousel-card-text">{text}</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
