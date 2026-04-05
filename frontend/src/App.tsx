import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAuth } from "./hooks/useAuth";
import { Layout } from "./components/Layout";
import { AuthGuard } from "./components/AuthGuard";
import { Login } from "./pages/Login";
import { AskMeAnything } from "./pages/AskMeAnything";
import { YourDocuments } from "./pages/YourDocuments";
import { AdminPanel } from "./pages/AdminPanel";

export default function App() {
  const { user, loading, githubEnabled, loginInvite, logout } = useAuth();

  return (
    <BrowserRouter>
      <Layout user={user} onLogout={logout}>
        <Routes>
          <Route path="/" element={<AskMeAnything />} />
          <Route
            path="/login"
            element={
              user ? <Navigate to="/" replace /> : (
                <Login onLoginInvite={loginInvite} githubEnabled={githubEnabled} />
              )
            }
          />
          <Route
            path="/documents"
            element={
              <AuthGuard user={user} loading={loading}>
                <YourDocuments />
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
