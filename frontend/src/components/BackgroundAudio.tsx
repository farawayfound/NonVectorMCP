import { useEffect, useRef } from "react";

const TRACK_PATH =
  "/uploads/media/" + encodeURIComponent("A-SIDE - STAY - INSTRUMENTAL.wav");

/** Site-wide loop; starts muted for autoplay policy, unmutes after first user gesture. */
export function BackgroundAudio() {
  const ref = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const el = ref.current;
    if (!el) return;

    el.volume = 0.35;
    el.muted = true;

    const unmute = () => {
      el.muted = false;
      void el.play().catch(() => {});
      window.removeEventListener("pointerdown", unmute);
      window.removeEventListener("keydown", unmute);
    };
    window.addEventListener("pointerdown", unmute);
    window.addEventListener("keydown", unmute);

    void el.play().catch(() => {});

    return () => {
      window.removeEventListener("pointerdown", unmute);
      window.removeEventListener("keydown", unmute);
    };
  }, []);

  if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return null;
  }

  return (
    <audio
      ref={ref}
      src={TRACK_PATH}
      loop
      preload="metadata"
      aria-hidden="true"
      style={{
        position: "fixed",
        width: 0,
        height: 0,
        opacity: 0,
        pointerEvents: "none",
      }}
    />
  );
}
