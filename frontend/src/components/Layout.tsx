import { Link, useLocation } from "react-router-dom";
import type { User } from "../types";

interface Props {
  user: User | null;
  onLogout: () => void;
  children: React.ReactNode;
}

export function Layout({ user, onLogout, children }: Props) {
  const location = useLocation();

  const navItems = [
    { path: "/", label: "Ask Me Anything" },
    ...(user ? [{ path: "/documents", label: "Your Documents" }] : []),
    { path: "/about", label: "About" },
    ...(user?.role === "admin" ? [{ path: "/admin", label: "Admin" }] : []),
  ];

  return (
    <div className="app-layout">
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
          <Link
            to="/resume"
            className={`header-resume-link${location.pathname === "/resume" ? " active" : ""}`}
          >
            My Resume
          </Link>
          {user ? (
            <>
              <span className="user-name">{user.display_name || user.github_username || "Guest"}</span>
              <button onClick={onLogout} className="btn btn-sm">Logout</button>
            </>
          ) : (
            <Link to="/login" className="btn btn-sm btn-primary">Login</Link>
          )}
        </div>
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}
