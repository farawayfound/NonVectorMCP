import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import type { User } from "../types";
import { RequestAccessModal } from "./RequestAccessModal";
import { BackgroundAudio } from "./BackgroundAudio";

interface Props {
  user: User | null;
  onLogout: () => void;
  children: React.ReactNode;
}

export function Layout({ user, onLogout, children }: Props) {
  const location = useLocation();
  const [showAccessModal, setShowAccessModal] = useState(false);

  const navItems = [
    { path: "/resume", label: "My Resume" },
    { path: "/", label: "Ask Me Anything" },
    ...(user ? [{ path: "/workspace", label: "Workspace" }] : []),
    ...(user ? [{ path: "/library", label: "Library" }] : []),
    { path: "/about", label: "About" },
    ...(user?.role === "admin" ? [{ path: "/admin", label: "Admin" }] : []),
  ];

  return (
    <div className="app-layout">
      <BackgroundAudio />
      <header className="app-header">
        <div className="header-left">
          <Link to="/" className="logo">ChunkyPotato</Link>
          <nav className="nav-links">
            {navItems.map((item) => (
              <Link
                key={item.path}
                to={item.path}
                className={location.pathname === item.path ? "active" : ""}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="header-right">
          {user ? (
            <>
              <span className="user-name">{user.display_name || user.github_username || "Guest"}</span>
              <button onClick={onLogout} className="btn btn-sm">Logout</button>
            </>
          ) : (
            <>
              <button
                onClick={() => setShowAccessModal(true)}
                className="btn btn-request-access"
              >
                <span>
                  Request{" "}
                  <span className="request-access-emphasis">free</span>{" "}
                  access to{" "}
                  <span className="request-access-emphasis">more</span>{" "}
                  features!
                </span>
              </button>
              <Link to="/login" className="btn btn-sm btn-primary">Login</Link>
            </>
          )}
        </div>
      </header>
      <main className="app-main">{children}</main>
      {showAccessModal && (
        <RequestAccessModal onClose={() => setShowAccessModal(false)} />
      )}
    </div>
  );
}
