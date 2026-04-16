import type { ChatPhase } from "../hooks/useChat";

interface Props {
  phase: ChatPhase;
  /** Live model reasoning text while in thinking / early answering. */
  thinking?: string;
  /** After first answer token: collapse thinking strip to one line in the status area. */
  minimizeThinking?: boolean;
}

const STAGES: { key: ChatPhase; label: string }[] = [
  { key: "sending", label: "Processing prompt" },
  { key: "searching", label: "Searching index" },
  { key: "thinking", label: "Thinking" },
  { key: "answering", label: "Generating response" },
];

function phaseIndex(phase: ChatPhase): number {
  return STAGES.findIndex((s) => s.key === phase);
}

export function ChatProgress({ phase, thinking = "", minimizeThinking = false }: Props) {
  if (phase === "idle") return null;

  const active = phaseIndex(phase);
  const showThinking =
    thinking.length > 0 &&
    (phase === "thinking" || phase === "searching" || phase === "sending" || phase === "answering");

  return (
    <div className="chat-progress">
      {STAGES.map((stage, i) => {
        let cls = "progress-step";
        if (i < active) cls += " done";
        else if (i === active) cls += " active";
        return (
          <div key={stage.key} className={cls}>
            <span className="progress-dot" />
            <span className="progress-label">{stage.label}</span>
          </div>
        );
      })}
      {showThinking && (
        <div
          className={
            "chat-progress-thinking" +
            (minimizeThinking && phase === "answering" ? " chat-progress-thinking--min" : "")
          }
        >
          {thinking}
        </div>
      )}
    </div>
  );
}
