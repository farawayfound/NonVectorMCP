import type { ChatMessage as Msg } from "../types";

interface Props {
  message: Msg;
}

export function ChatMessage({ message }: Props) {
  const isUser = message.role === "user";
  return (
    <div className={`chat-message ${isUser ? "user" : "assistant"}`}>
      <div className="message-role">{isUser ? "You" : "ChunkyLink"}</div>
      <div className="message-content">{message.content || "\u00A0"}</div>
    </div>
  );
}
