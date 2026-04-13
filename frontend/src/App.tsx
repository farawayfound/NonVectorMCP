import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { Layout } from "./components/Layout";
import { AuthGuard } from "./components/AuthGuard";
import { Login } from "./pages/Login";
import { AskMeAnything } from "./pages/AskMeAnything";
import { Workspace } from "./pages/Workspace";
import { AdminPanel } from "./pages/AdminPanel";
import { About } from "./pages/About";
import { MyResume } from "./pages/MyResume";
import { Library } from "./pages/Library";

export default function App() {
  const { user, loading, githubEnabled, loginInvite, logout } = useAuth();

  return (
    <BrowserRouter>
      <Layout user={user} onLogout={logout}>
        <Routes>
          <Route path="/" element={<AskMeAnything />} />
          <Route path="/about" element={<About />} />
          <Route path="/resume" element={<MyResume />} />
          <Route
            path="/login"
            element={
              user ? <Navigate to="/" replace /> : (
                <Login onLoginInvite={loginInvite} githubEnabled={githubEnabled} />
              )
            }
          />
          <Route
            path="/workspace"
            element={
              <AuthGuard user={user} loading={loading}>
                <Workspace />
              </AuthGuard>
            }
          />
          <Route path="/documents" element={<Navigate to="/workspace" replace />} />
          <Route
            path="/library"
            element={
              <AuthGuard user={user} loading={loading}>
                <Library />
              </AuthGuard>
            }
          />
          <Route
            path="/admin"
            element={
              <AuthGuard user={user} loading={loading} requireAdmin>
                <AdminPanel />
              </AuthGuard>
            }
          />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
