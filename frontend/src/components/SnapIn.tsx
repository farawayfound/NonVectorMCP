import { useEffect, useRef } from "react";

type Edge = "left" | "right" | "top" | "bottom";

interface Props {
  children: React.ReactNode;
  from?: Edge;
  delay?: number;
  className?: string;
  style?: React.CSSProperties;
  skip?: boolean;
}

// How long the snap-in CSS transition takes (must match index.css)
const TRANSITION_MS = 620;

/**
 * Snaps a section in from the given viewport edge on mount, then strips
 * the transform so scroll has no effect on the element afterward.
 */
export function SnapIn({ children, from = "bottom", delay = 0, className = "", style, skip = false }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (skip || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.classList.add("snap-in--settled");
      return;
    }

    // Phase 1: trigger the slide in
    const t1 = setTimeout(() => {
      el.classList.add("snap-in--visible");

      // Phase 2: after transition finishes, lock element in place with no transform
      const t2 = setTimeout(() => {
        el.classList.add("snap-in--settled");
      }, TRANSITION_MS + 50);

      return () => clearTimeout(t2);
    }, delay);

    return () => clearTimeout(t1);
  }, [delay, skip]);

  return (
    <div
      ref={ref}
      className={`snap-in snap-in--from-${from}${className ? ` ${className}` : ""}`}
      style={style}
    >
      {children}
    </div>
  );
}
