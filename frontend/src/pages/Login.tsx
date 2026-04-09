import { useState } from "react";
import { useNavigate } from "react-router-dom";

interface Props {
  onLoginInvite: (code: string) => Promise<void>;
  githubEnabled: boolean;
}

export function Login({ onLoginInvite, githubEnabled }: Props) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError("");
    try {
      await onLoginInvite(code.trim().toUpperCase());
      navigate("/");
    } catch (err: any) {
      setError(err.message || "Invalid invite code");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h1>ChunkyPotato</h1>
        <p className="subtitle">Document RAG System</p>

        {githubEnabled && (
          <>
            <a href="/api/auth/github/login" className="btn btn-primary btn-block">
              Sign in with GitHub
            </a>
            <div className="divider"><span>or</span></div>
          </>
        )}

        <form onSubmit={handleInvite}>
          <label htmlFor="invite-code">Invite Code</label>
          <input
            id="invite-code"
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Enter invite code"
            maxLength={12}
            autoComplete="off"
            autoFocus={!githubEnabled}
          />
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn btn-block" disabled={loading || !code.trim()}>
            {loading ? "Validating..." : "Enter"}
          </button>
        </form>
      </div>
    </div>
  );
}
