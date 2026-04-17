import { useState, useCallback } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { User } from "../types";
import { RequestAccessModal } from "./RequestAccessModal";
import { BackgroundAudio } from "./BackgroundAudio";
import { usePageTransition } from "./PageTransitionContext";

interface Props {
  user: User | null;
  onLogout: () => void;
  children: React.ReactNode;
}

export function Layout({ user, onLogout, children }: Props) {
  const location = useLocation();
  const navigate = useNavigate();
  const { isExiting, exitDirection, startExit } = usePageTransition();
  const [showAccessModal, setShowAccessModal] = useState(false);

  const navItems = [
    { path: "/resume", label: "My Resume" },
    { path: "/", label: "Ask Me Anything" },
    ...(user ? [{ path: "/workspace", label: "Workspace" }] : []),
    ...(user ? [{ path: "/library", label: "Library" }] : []),
    { path: "/about", label: "About" },
    ...(user?.role === "admin" ? [{ path: "/admin", label: "Admin" }] : []),
  ];

  const handleNavClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, targetPath: string) => {
      if (targetPath === location.pathname) return;
      e.preventDefault();

      const currentIdx = navItems.findIndex((n) => n.path === location.pathname);
      const targetIdx = navItems.findIndex((n) => n.path === targetPath);

      // Pages to the right → rotate UP; pages to the left → rotate DOWN
      const direction: "up" | "down" = targetIdx > currentIdx ? "up" : "down";

      startExit(direction).then(() => {
        navigate(targetPath);
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [location.pathname, navItems, startExit, navigate],
  );

  const exitClass = isExiting ? `app-main--exit-${exitDirection}` : "";

  return (
    <div className="app-layout">
      <BackgroundAudio />
      <header className="app-header">
        <div className="header-left">
          <Link to="/" className="logo">ChunkyPotato</Link>
          <nav className="nav-links">
            {navItems.map((item) => (
              <a
                key={item.path}
                href={item.path}
                className={location.pathname === item.path ? "active" : ""}
                onClick={(e) => handleNavClick(e, item.path)}
              >
                {item.label}
              </a>
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
      <main className={`app-main ${exitClass}`}>{children}</main>
      {showAccessModal && (
        <RequestAccessModal onClose={() => setShowAccessModal(false)} />
      )}
    </div>
  );
}
