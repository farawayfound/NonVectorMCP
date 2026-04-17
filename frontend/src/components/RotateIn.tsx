import { useEffect, useRef } from "react";

interface Props {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  style?: React.CSSProperties;
}

// How long the rotate-in CSS transition takes (must match index.css)
const TRANSITION_MS = 550;

/**
 * Rotates 90° around the X-axis into view on mount, then strips the
 * transform entirely so scroll has no effect on the element afterward.
 */
export function RotateIn({ children, delay = 0, className = "", style }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.classList.add("rotate-in--settled");
      return;
    }

    // Phase 1: trigger the rotation in
    const t1 = setTimeout(() => {
      el.classList.add("rotate-in--visible");

      // Phase 2: after transition finishes, lock element in place with no transform
      const t2 = setTimeout(() => {
        el.classList.add("rotate-in--settled");
      }, TRANSITION_MS + 50);

      return () => clearTimeout(t2);
    }, delay);

    return () => clearTimeout(t1);
  }, [delay]);

  return (
    <div
      ref={ref}
      className={`rotate-in${className ? ` ${className}` : ""}`}
      style={style}
    >
      {children}
    </div>
  );
}
