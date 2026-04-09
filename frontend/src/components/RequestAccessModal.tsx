import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { requestAccess } from "../api/client";

interface Props {
  onClose: () => void;
}

export function RequestAccessModal({ onClose }: Props) {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;

    setStatus("sending");
    setMessage("");

    try {
      const data = await requestAccess(email.trim());
      setStatus("sent");
      setMessage(data.message || "Access code sent! Check your email.");
    } catch (err: any) {
      setStatus("error");
      setMessage(err.message || "Something went wrong. Please try again.");
    }
  };

  const handleGoToLogin = () => {
    onClose();
    navigate("/login");
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>&times;</button>

        <h2>Request Access</h2>
        <p className="modal-subtitle">
          Enter your email and we'll send you an access code.
        </p>

        {status === "sent" ? (
          <div className="modal-success">
            <p>{message}</p>
            <p className="modal-hint">
              Once you receive your code, use it on the login page to sign in.
            </p>
            <button onClick={handleGoToLogin} className="btn btn-primary btn-block">
              Go to Login
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <label htmlFor="access-email">Email address</label>
            <input
              id="access-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              autoFocus
              required
            />
            {status === "error" && <p className="error">{message}</p>}
            <button
              type="submit"
              className="btn btn-primary btn-block"
              disabled={status === "sending" || !email.trim()}
            >
              {status === "sending" ? "Sending..." : "Send Access Code"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
