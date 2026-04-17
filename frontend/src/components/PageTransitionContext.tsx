import { createContext, useCallback, useContext, useRef, useState } from "react";

export type FlipDirection = "up" | "down";

interface PageTransitionCtx {
  /** True while the page-exit rotation is running */
  isExiting: boolean;
  /** Direction the current page rotates out */
  exitDirection: FlipDirection;
  /**
   * Kick off a page-exit rotation. Resolves after the CSS transition
   * finishes (~400ms) so the caller can navigate.
   */
  startExit: (direction: FlipDirection) => Promise<void>;
}

const DURATION_MS = 400;

const Ctx = createContext<PageTransitionCtx>({
  isExiting: false,
  exitDirection: "up",
  startExit: async () => {},
});

export function PageTransitionProvider({ children }: { children: React.ReactNode }) {
  const [isExiting, setIsExiting] = useState(false);
  const [exitDirection, setExitDirection] = useState<FlipDirection>("up");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startExit = useCallback((direction: FlipDirection): Promise<void> => {
    return new Promise((resolve) => {
      setExitDirection(direction);
      setIsExiting(true);

      timerRef.current = setTimeout(() => {
        setIsExiting(false);
        resolve();
      }, DURATION_MS);
    });
  }, []);

  return (
    <Ctx.Provider value={{ isExiting, exitDirection, startExit }}>
      {children}
    </Ctx.Provider>
  );
}

export function usePageTransition() {
  return useContext(Ctx);
}
