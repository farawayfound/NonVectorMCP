import { useCallback, useEffect, useRef, useState } from "react";

const NUM_SLOTS = 9;
const STEP_DEG = 360 / NUM_SLOTS;
const RADIUS_PX = 280;
const AUTO_DEG_PER_SEC = 14;
/** Wheel spin scales with auto rate; lower = more damped. */
const WHEEL_SPIN_DAMP = 0.48;
const DRAG_DEG_PER_PX = 0.45;
const HOVER_LERP = 0.07;
const MAX_HOVER_TILT = 16;
const READABLE_COS = 0.72;
const EDGE_COS = 0.12;
/** Horizontal band from each edge of the wrap that counts as “side” for drag hints. */
const DRAG_HINT_EDGE_PX = 52;

export type SuggestionCarouselVisualMode = "intro" | "idle" | "pickHero" | "scatterAll";

type Props = {
  pool: string[];
  /** Source element is used for FLIP-style handoff to the AMA prompt card. */
  onPick: (question: string, slotIndex: number, sourceEl: HTMLButtonElement) => void;
  paused?: boolean;
  visualMode: SuggestionCarouselVisualMode;
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

/** Normalize wheel delta to pixel-like units (deltaMode-aware). */
function wheelDeltaYPixels(e: WheelEvent): number {
  let y = e.deltaY;
  if (e.deltaMode === WheelEvent.DOM_DELTA_LINE) y *= 16;
  else if (e.deltaMode === WheelEvent.DOM_DELTA_PAGE) y *= 400;
  return y;
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
  const wrapRef = useRef<HTMLDivElement>(null);
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
  const leftHintLitRef = useRef(false);
  const rightHintLitRef = useRef(false);
  const [leftHintLit, setLeftHintLit] = useState(false);
  const [rightHintLit, setRightHintLit] = useState(false);
  const [draggingUI, setDraggingUI] = useState(false);

  /** Pause auto-spin + slot refresh (intro / pick / scatter). */
  const freezeSpin = visualMode === "pickHero" || visualMode === "scatterAll" || visualMode === "intro";
  /** Block drag on empty stage + block stray clicks only during pick/scatter sequences. */
  const blockStageDrag = visualMode === "pickHero" || visualMode === "scatterAll";

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

      const wrap = wrapRef.current;
      let leftLit = false;
      let rightLit = false;
      if (wrap && !paused && !blockStageDrag && !draggingRef.current) {
        const wr = wrap.getBoundingClientRect();
        if (
          e.clientX >= wr.left &&
          e.clientX <= wr.right &&
          e.clientY >= wr.top &&
          e.clientY <= wr.bottom
        ) {
          const edge = Math.min(DRAG_HINT_EDGE_PX, wr.width * 0.11);
          const lx = e.clientX - wr.left;
          leftLit = lx < edge;
          rightLit = lx > wr.width - edge;
        }
      }
      if (leftLit !== leftHintLitRef.current) {
        leftHintLitRef.current = leftLit;
        setLeftHintLit(leftLit);
      }
      if (rightLit !== rightHintLitRef.current) {
        rightHintLitRef.current = rightLit;
        setRightHintLit(rightLit);
      }
    };

    const onLeave = () => {
      targetHoverXRef.current = 0;
      targetHoverYRef.current = 0;
    };

    const onUp = () => {
      draggingRef.current = false;
      setDraggingUI(false);
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
  }, [paused, blockStageDrag]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;

    const onWheel = (e: WheelEvent) => {
      if (paused || blockStageDrag) return;
      const r = stage.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      ) {
        return;
      }
      e.preventDefault();
      const dy = wheelDeltaYPixels(e);
      // Scroll down (dy > 0) → clockwise, same sign as auto-spin.
      const k = (AUTO_DEG_PER_SEC / 100) * WHEEL_SPIN_DAMP;
      spinDegRef.current += dy * k;
    };

    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, [paused, blockStageDrag]);

  useEffect(() => {
    const pivot = pivotRef.current;
    if (!pivot) return;

    const tick = (t: number) => {
      if (lastTRef.current === null) lastTRef.current = t;
      const dt = Math.min((t - lastTRef.current) / 1000, 0.05);
      lastTRef.current = t;

      if (!paused && !freezeSpin && !pointerOverStageRef.current && !draggingRef.current) {
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
        } else if (!freezeSpin) {
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
          const allowClick = readable && !paused && !blockStageDrag;
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
  }, [paused, refreshSlot, freezeSpin, blockStageDrag]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (paused || blockStageDrag) return;
    const t = e.target as HTMLElement;
    if (t.closest(".suggestion-carousel-card")) return;
    draggingRef.current = true;
    dragMovedRef.current = false;
    lastPointerXRef.current = e.clientX;
    setDraggingUI(true);
    stageRef.current?.setPointerCapture(e.pointerId);
  };

  const onCardPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    draggingRef.current = false;
    dragMovedRef.current = false;
    setDraggingUI(false);
  };

  const onCardClick = (slot: number, e: React.MouseEvent<HTMLButtonElement>) => {
    if (paused || blockStageDrag || dragMovedRef.current) return;
    const rel = wrapRelDeg(slot * STEP_DEG + spinDegRef.current);
    const cosF = Math.cos((rel * Math.PI) / 180);
    if (cosF < READABLE_COS) return;
    onPick(texts[slot] ?? "", slot, e.currentTarget);
  };

  const stageClass =
    "suggestion-carousel-stage" +
    (visualMode === "pickHero" ? " suggestion-carousel-stage--pick" : "") +
    (visualMode === "scatterAll" ? " suggestion-carousel-stage--scatter-all" : "") +
    (blockStageDrag ? " suggestion-carousel-stage--block-drag" : "");

  const wrapClass =
    "suggestion-carousel-wrap" +
    (draggingUI ? " suggestion-carousel-wrap--dragging" : "") +
    (paused || blockStageDrag ? " suggestion-carousel-wrap--hints-muted" : "");

  const hintSideLit = !paused && !blockStageDrag && !draggingUI;
  const leftSideClass =
    "suggestion-carousel-hint-side suggestion-carousel-hint-side--left" +
    (leftHintLit && hintSideLit ? " suggestion-carousel-hint-side--lit" : "");
  const rightSideClass =
    "suggestion-carousel-hint-side suggestion-carousel-hint-side--right" +
    (rightHintLit && hintSideLit ? " suggestion-carousel-hint-side--lit" : "");

  return (
    <div className="suggestion-carousel" aria-label="Suggested questions carousel">
      <div ref={wrapRef} className={wrapClass}>
        <div className="suggestion-carousel-hints" aria-hidden="true">
          <div className={leftSideClass}>
            <div className="suggestion-carousel-hint-anchor">
              <span className="suggestion-carousel-hint-bar" />
              <span className="suggestion-carousel-hint-chevron suggestion-carousel-hint-chevron-in">
                {">"}
              </span>
              <span className="suggestion-carousel-hint-chevron suggestion-carousel-hint-chevron-out">
                {"<"}
              </span>
            </div>
          </div>
          <div className={rightSideClass}>
            <div className="suggestion-carousel-hint-anchor">
              <span className="suggestion-carousel-hint-bar" />
              <span className="suggestion-carousel-hint-chevron suggestion-carousel-hint-chevron-in">
                {"<"}
              </span>
              <span className="suggestion-carousel-hint-chevron suggestion-carousel-hint-chevron-out">
                {">"}
              </span>
            </div>
          </div>
        </div>
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
              if (isHero) flipMod += " suggestion-carousel-flip--hero-handoff";
              else if (isLeftExit) flipMod += " suggestion-carousel-flip--exit-left";
              else if (isRightExit) flipMod += " suggestion-carousel-flip--exit-right";
              else if (visualMode === "scatterAll") {
                flipMod += ` suggestion-carousel-flip--scatter-${i % 4}`;
              }

              const flipStyle: React.CSSProperties = {};
              if (visualMode === "intro") {
                flipStyle.animationDelay = `${i * 0.04}s`;
              }

              return (
                <div
                  key={i}
                  className="suggestion-carousel-cell"
                  style={{ transform: `rotateY(${i * STEP_DEG}deg) translateZ(${RADIUS_PX}px)` }}
                >
                  <div className={`suggestion-carousel-flip${flipMod}`} style={flipStyle}>
                    <button
                      type="button"
                      ref={(el) => {
                        cardRefs.current[i] = el;
                      }}
                      className="suggestion-carousel-card"
                      disabled={paused}
                      onPointerDown={onCardPointerDown}
                      onClick={(e) => onCardClick(i, e)}
                    >
                      <span className="suggestion-carousel-card-text-clip">
                        <span className="suggestion-carousel-card-text">{text}</span>
                      </span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
